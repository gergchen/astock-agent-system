const vscode = require('vscode');

function activate(context) {
    let currentPanel = undefined;

    const disposable = vscode.commands.registerCommand('astock.openChat', () => {
        const columnToShowIn = vscode.window.activeTextEditor
            ? vscode.ViewColumn.Beside
            : vscode.ViewColumn.Active;

        if (currentPanel) {
            currentPanel.reveal(columnToShowIn);
            return;
        }

        currentPanel = vscode.window.createWebviewPanel(
            'astockChat',
            'A股交易助手',
            columnToShowIn,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
            }
        );

        currentPanel.webview.html = getHtml(currentPanel.webview);
        currentPanel.onDidDispose(() => { currentPanel = undefined; });
    });

    context.subscriptions.push(disposable);
}

function getHtml(webview) {
    const cspSource = webview.cspSource;
    const chatUrl = 'http://localhost:8080/chat';

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="
        default-src 'none';
        style-src ${cspSource} 'unsafe-inline';
        script-src 'unsafe-inline';
        frame-src http://localhost:8080;
        img-src ${cspSource} data:;
    ">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { height: 100vh; width: 100vw; overflow: hidden; background: #1a1b1e; }
        iframe { width: 100%; height: 100%; border: none; }
        .error { display: none; }
    </style>
</head>
<body>
    <iframe id="chat" src="${chatUrl}"></iframe>
    <script>
        document.getElementById('chat').onerror = function() {
            document.body.innerHTML = '<div style="color:#e1e1e3;padding:20px;font-family:sans-serif;">'
                + '<h2>无法连接</h2>'
                + '<p>请确认交易助手服务已启动:</p>'
                + '<code>python -m managed_agents.api.server</code>'
                + '</div>';
        };
    </script>
</body>
</html>`;
}

module.exports = { activate };
