const childProcess = require("child_process");
const path = require("path");
const vscode = require("vscode");

function isLpDocument(document) {
  return (
    document &&
    document.uri &&
    document.uri.scheme === "file" &&
    document.fileName.toLowerCase().endsWith(".lp")
  );
}

class BackendClient {
  constructor(context) {
    this.context = context;
  }

  getBackendScriptPath() {
    return path.join(this.context.extensionPath, "python_backend", "lp_backend.py");
  }

  getPythonPath(filePath) {
    return (
      vscode.workspace
        .getConfiguration("lp", filePath ? vscode.Uri.file(filePath) : undefined)
        .get("pythonPath") || "python"
    );
  }

  getScriptsRoot(filePath) {
    const config = vscode.workspace.getConfiguration(
      "lp",
      filePath ? vscode.Uri.file(filePath) : undefined
    );
    const configuredValue =
      config.get("backendScriptsRoot") ||
      "${workspaceFolder}/skills/logic-language/scripts";
    const resolvedConfigured = this.resolveConfiguredPath(configuredValue, filePath);
    if (resolvedConfigured) {
      return resolvedConfigured;
    }

    return path.resolve(this.context.extensionPath, "..", "..", "scripts");
  }

  resolveConfiguredPath(configuredValue, filePath) {
    if (!configuredValue) {
      return undefined;
    }

    const workspaceFolder = filePath
      ? vscode.workspace.getWorkspaceFolder(vscode.Uri.file(filePath))
      : vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
    const workspaceRoot = workspaceFolder && workspaceFolder.uri.fsPath;

    if (configuredValue.includes("${workspaceFolder}")) {
      if (!workspaceRoot) {
        return undefined;
      }
      return path.normalize(
        configuredValue.replace(/\$\{workspaceFolder\}/g, workspaceRoot)
      );
    }

    return path.normalize(configuredValue);
  }

  runJsonCommand(args, options = {}) {
    const filePath = options.filePath;
    const pythonPath = this.getPythonPath(filePath);
    const scriptsRoot = this.getScriptsRoot(filePath);
    const backendScript = this.getBackendScriptPath();
    const pythonPathEnv = process.env.PYTHONPATH
      ? [scriptsRoot, process.env.PYTHONPATH].join(path.delimiter)
      : scriptsRoot;

    return new Promise((resolve, reject) => {
      const child = childProcess.spawn(
        pythonPath,
        [backendScript, ...args],
        {
          cwd: filePath ? path.dirname(filePath) : this.context.extensionPath,
          env: {
            ...process.env,
            PYTHONPATH: pythonPathEnv
          },
          windowsHide: true
        }
      );

      let stdout = "";
      let stderr = "";

      child.stdout.on("data", (chunk) => {
        stdout += chunk.toString("utf8");
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk.toString("utf8");
      });
      child.on("error", (error) => {
        reject(error);
      });
      child.on("close", (code) => {
        if (code !== 0) {
          const detail = stderr.trim() || stdout.trim() || `backend exited with code ${code}`;
          reject(new Error(detail));
          return;
        }

        try {
          resolve(JSON.parse(stdout));
        } catch (error) {
          reject(
            new Error(
              `failed to parse backend JSON output: ${error instanceof Error ? error.message : String(error)}`
            )
          );
        }
      });

      if (options.stdin) {
        child.stdin.write(options.stdin);
      }
      child.stdin.end();
    });
  }

  diagnostics(document) {
    return this.runJsonCommand(
      ["diagnostics", "--file", document.fileName, "--stdin"],
      {
        filePath: document.fileName,
        stdin: document.getText()
      }
    );
  }

  indexFile(filePath) {
    return this.runJsonCommand(["index-file", "--file", filePath], {
      filePath
    });
  }

  queryClass(filePath, className, full) {
    const args = ["query-class", "--file", filePath, "--class", className];
    if (full) {
      args.push("--full");
    }
    return this.runJsonCommand(args, { filePath });
  }

  queryInheritance(filePath, className) {
    const args = ["query-inheritance", "--file", filePath];
    if (className) {
      args.push("--class", className);
    }
    return this.runJsonCommand(args, { filePath });
  }
}

module.exports = {
  BackendClient,
  isLpDocument
};
