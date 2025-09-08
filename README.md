本机的 MCP 工具管理器，可以批量启动多个 MCP。

目标是将各种类型的MCP都集中起来，对外提供统一的 streamableHTTP 服务，且端口也批量管理起来。



计划实现的功能：

- [x] 直接启动python的MCP程序；
- [x] 将stdio、sse等外部服务代理为本机 streamableHTTP 并放在特定端口；
- [x] 将 npm 代理为本机 streamableHTTP 服务；
- [x] 设置端口号
- [ ] 制作UI，实现动态管理
- [x] 开发网页 WebUI 实现在线管理
- [ ] MCP工具直接手动调用（不需要AI执行）的功能；



使用方法：

uv run local_mcp_manager_flask.py



