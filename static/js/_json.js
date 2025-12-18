function formatAndDisplay() {
    const input = document.getElementById('jsonInput').value.trim();
    const outputEl = document.getElementById('jsonOutput');

    if (!input) {
        outputEl.innerHTML = '<div class="json-error">⚠️ 输入为空</div>';
        return;
    }

    try {
        // 1. 解析验证 JSON
        const obj = JSON.parse(input);
        // 2. 格式化为带缩进的字符串（2空格）
        const formatted = JSON.stringify(obj, null, 2);
        // 3. 高亮渲染（安全：逐字符转义后插入 span）
        const highlighted = highlightJSON(formatted);
        outputEl.innerHTML = `<pre class="json-display">${highlighted}</pre>`;
    } catch (e) {
        outputEl.innerHTML = `<div class="json-error">❌ JSON 解析错误：${e.message}</div>`;
    }
}

function highlightJSON(jsonStr) {
    // 转义 HTML 特殊字符（防 XSS）
    const escape = s => s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');

    // 基础语法高亮正则（简化但足够准确）
    return escape(jsonStr)
        .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, (match) => {
        let cls = 'json-number';
        if (/^"/.test(match)) {
            if (/:$/.test(match)) {
            cls = 'json-key';
            } else {
            cls = 'json-string';
            }
        } else if (/true|false/.test(match)) {
            cls = 'json-boolean';
        } else if (/null/.test(match)) {
            cls = 'json-null';
        }
        return `<span class="${cls}">${match}</span>`;
    });
}