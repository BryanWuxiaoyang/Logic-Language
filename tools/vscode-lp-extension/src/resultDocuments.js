const vscode = require("vscode");

class ResultDocumentProvider {
  constructor() {
    this.documents = new Map();
    this.emitter = new vscode.EventEmitter();
    this.onDidChange = this.emitter.event;
  }

  createDocument(title, body) {
    const slug = title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "lp-result";
    const uri = vscode.Uri.parse(`lp-query:${slug}-${Date.now()}.txt`);
    const content = `${title}\n${"=".repeat(title.length)}\n\n${body}`;
    this.documents.set(uri.toString(), content);
    this.emitter.fire(uri);
    return uri;
  }

  provideTextDocumentContent(uri) {
    return this.documents.get(uri.toString()) || "Result document not found.";
  }
}

module.exports = {
  ResultDocumentProvider
};
