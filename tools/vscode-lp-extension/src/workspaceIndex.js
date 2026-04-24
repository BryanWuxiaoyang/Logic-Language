const vscode = require("vscode");

function normalizeFilePath(filePath) {
  return filePath.toLowerCase();
}

class WorkspaceIndex {
  constructor(backendClient) {
    this.backendClient = backendClient;
    this.entriesByFile = new Map();
  }

  async rebuild() {
    this.entriesByFile.clear();
    const files = await vscode.workspace.findFiles(
      "**/*.lp",
      "**/{.git,node_modules}/**"
    );

    for (const file of files) {
      await this.refreshFile(file.fsPath);
    }

    return this.entriesByFile.size;
  }

  async refreshFile(filePath) {
    const entry = await this.backendClient.indexFile(filePath);
    this.entriesByFile.set(normalizeFilePath(filePath), entry);
    return entry;
  }

  removeFile(filePath) {
    this.entriesByFile.delete(normalizeFilePath(filePath));
  }

  getEntry(filePath) {
    return this.entriesByFile.get(normalizeFilePath(filePath));
  }

  getClassesForFile(filePath) {
    const entry = this.getEntry(filePath);
    return entry ? entry.classes || [] : [];
  }

  getWorkspaceClassCandidates() {
    const candidates = [];
    for (const entry of this.entriesByFile.values()) {
      for (const className of entry.classes || []) {
        candidates.push({
          className,
          filePath: entry.file
        });
      }
    }

    candidates.sort((left, right) => {
      const byClass = left.className.localeCompare(right.className);
      if (byClass !== 0) {
        return byClass;
      }
      return left.filePath.localeCompare(right.filePath);
    });
    return candidates;
  }
}

module.exports = {
  WorkspaceIndex
};
