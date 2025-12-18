import multiprocessing as mp
import asyncio
import os
import json
import time
import signal
import sys
from fastmcp import FastMCP
from fastmcp import Client
from fastmcp.server.proxy import ProxyClient

#
VERSION = 'v0.3.0'
#
# ========== Entry ==========

def mcp_stdio_to_http(json_str, host:str, port:int, name:str='MCP', cwd:str=None):
    """
    Run MCP with npm / python, must work in stdio mode.
    
    Output: in streamableHTTP mode.
    """
    if cwd is not None:
        os.chdir(cwd)
    #
    conf = json.loads(json_str)
    try:
        client = ProxyClient(conf)
        local_proxy = FastMCP.as_proxy(
            client,
            name=name,
        )
        tar = local_proxy.run(transport='http', host=host, port=int(port))
        return tar
    except:
        client = Client(conf)
        local_proxy = FastMCP.as_proxy(
            client,
            name=name,
        )
        tar = local_proxy.run(transport='http', host=host, port=int(port))
        return tar

class ProcessManager:
    """ 
    MCP Service Manager, background.
    """
    def __init__(self, services):
        self.VERSION = VERSION
        self.services = services  
        self.name_index = {svc["name"]: i for i, svc in enumerate(self.services)}  
    
    def reload_conf(self, services=None):
        """ 
        重新加载配置文件，执行此操作会先关停服务。
        """
        if services is None:
            services = load_conf()
        self.stop_all_running_services()  # 必须先关停，再刷新
        self.services = services  
        self.name_index = {svc["name"]: i for i, svc in enumerate(self.services)}  

    def refresh_svc_status(self):
        """ 
        Refresh is_alive status
        """
        for svc in self.services:
            proc = svc.get("process")
            alive = proc.is_alive() if isinstance(proc, mp.Process) else False
            svc["is_alive"] = alive

    # ---------- process control ----------
    def _start_service(self, svc):
        """ 
        svc: dict 
        """
        if svc["is_alive"]:
            return
        # if olds not alive, clean 
        if isinstance(svc.get("process"), mp.Process):
            if svc["process"].is_alive():
                return
            else:
                try:
                    if svc["process"].exitcode is None:
                        svc["process"].join(timeout=3)
                except Exception:
                    pass

        # new process
        try:
            svc["process"].start()
        except:
            p = mp.Process(
                target=mcp_stdio_to_http,
                args=(
                    svc["conf"], 
                    svc['host'],
                    svc["port"], 
                    svc["name"],
                    svc['cwd'],
                ),
                daemon=False,  # The typical service process does not recommend daemon, allowing for controlled exit.
            )
            p.start()
            svc["process"] = p
            svc["is_alive"] = True

    def _stop_service(self, svc, timeout=3.0):
        proc = svc.get("process")
        if not isinstance(proc, mp.Process):
            svc["is_alive"] = False
            return
        if not proc.is_alive():
            svc["is_alive"] = False
            return
        try:
            # stop
            proc.terminate()
            proc.join(timeout=timeout)
            if proc.is_alive():
                if os.name == "posix":
                    try:
                        os.kill(proc.pid, signal.SIGKILL)
                    except Exception:
                        pass
                else:
                    # no SIGKILL in Windows, have to terminate again.
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    proc.join(timeout=1.0)
        except Exception as e:
            print(f"Stop service {svc['name']} error: {e}")
        finally:
            svc["is_alive"] = False

    def start_all_enabled_services(self):
        """
        Start all 'is_alive' processes
        """
        for svc in self.services:
            if svc.get("is_enabled", False):
                self._start_service(svc)

    def stop_all_running_services(self):
        for svc in self.services:
            if svc.get("is_alive", False):
                self._stop_service(svc)

    def count_alive(self):
        """ 
        check 'is_alive' status
        """
        n_alive = 0
        for svc in self.services:
            proc = svc.get("process")
            alive = proc.is_alive() if isinstance(proc, mp.Process) else False
            if alive:
                n_alive += 1
        return n_alive

    async def get_tools_by_name(self, svc_name):
        """
        获取MCP介绍信息

        返回 json 格式的结果
        """
        dict_res = {}
        lst_svc = [s for s in self.services if s.get("name")==svc_name]
        if len(lst_svc)>0:
            svc = lst_svc[0]
            if svc['host'].startswith("http"):
                host = svc['host']
            elif svc['host'] in ['127.0.0.1', '0.0.0.0']:
                host = 'http://127.0.0.1'

            dict_conf = {"mcp":{
                "url": f"{host}:{svc['port']}/mcp"
            }}

            async with Client(dict_conf) as client:
                try:
                    dict_res['tools'] = [t.model_dump() for t in await client.list_tools()]
                except:
                    dict_res['tools'] = [str(t) for t in await client.list_tools()]
                # dict_res['resources'] = [t.modeawait client.list_resources()
        
        print(f"[get_tools_by_name] dict_res = {dict_res}")
        try:
            return json.dumps(dict_res['tools'], indent=2, ensure_ascii=False)
        except:
            return str(dict_res['tools'])
    
    async def get_tools_all(self):
        """ 
        获取全部 MCP介绍信息
        """
        dict_tools = {}
        lst_tasks = [self.get_tools_by_name(s.get("name")) for s in self.services]
        results = await asyncio.gather(*lst_tasks, return_exceptions=True)
        return str(results)
        
    async def call_tool(self, svc_name:str, tool_name:str, tool_params:str):
        """ 
        调用工具
        """
        dict_res = {}
        lst_svc = [s for s in self.services if s.get("name")==svc_name]
        if len(lst_svc)>0:
            svc = lst_svc[0]
            if svc['host'].startswith("http"):
                host = svc['host']
            elif svc['host'] in ['127.0.0.1', '0.0.0.0']:
                host = 'http://127.0.0.1'

            dict_conf = {"mcp":{
                "url": f"{host}:{svc['port']}/mcp"
            }}

            async with Client(dict_conf) as client:
                tool_result = await client.call_tool(tool_name, json.loads(tool_params))
                try:
                    dict_res['tool_result'] = tool_result.model_dump()
                except:
                    dict_res['tool_result'] = str(tool_result)
        
        print(f"[call_tool] dict_res = {dict_res}")
        return json.dumps(dict_res, ensure_ascii=False)

def load_conf(filepath = 'mcp_conf.json'):
    """
    加载配置文件的内容。

    返回：列表，内容是配置文件 mcpServers 下面的每一项服务。
    """
    lst_mprocesses = []
    #
    with open(filepath,'r',encoding='utf8') as f:
        dict_conf = json.load(f)
    #
    mcp_servers = dict_conf.get("mcpServers")
    #
    # 补充一些信息
    for ms_key in mcp_servers.keys():
        ms_value = mcp_servers[ms_key]
        lst_mprocesses.append({
            'name':ms_value.get("name", ms_key),
            'process':None,
            'in_type':"stdio" if ms_value.get("command",False) else ms_value.get("type", "sse" if ms_value.get("url","").find("/sse")>0 else "http"),
            'out_type': 'http',
            'conf': json.dumps({"mcpServers":{ms_key:ms_value}}, ensure_ascii=False),
            'host': ms_value.get("host", '127.0.0.1'),
            'cwd': ms_value.get("cwd", None),
            'port': ms_value.get("out_port", "null"),
            "is_enabled": ms_value.get("isActive", True),
            "is_alive": False,
        })
    return lst_mprocesses

def load_config_raw(filepath='mcp_conf.json'):
    """
    加载配置文件的原始内容

    Args:
        filepath: 配置文件路径

    Returns:
        str: 配置文件的原始 JSON 内容

    Raises:
        FileNotFoundError: 配置文件不存在
        json.JSONDecodeError: JSON 格式错误
        Exception: 其他读取错误
    """
    # 如果主配置文件不存在，尝试使用示例文件
    if not os.path.exists(filepath):
        if os.path.exists('mcp_conf.example.json'):
            filepath = 'mcp_conf.example.json'
        else:
            raise FileNotFoundError(f"Configuration file not found: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def save_config_raw(config_content:str, filepath='mcp_conf.json'):
    """
    保存配置文件的原始内容

    Args:
        config_content: 配置内容的JSON字符串
        filepath: 配置文件路径

    Returns:
        dict: 保存结果

    Raises:
        json.JSONDecodeError: JSON 格式错误
        ValueError: 配置结构错误
        Exception: 其他保存错误
    """
    # 验证 JSON 格式
    try:
        config_data = json.loads(config_content)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Invalid JSON format: {str(e)}", e.doc, e.pos)

    # 验证配置结构
    if not isinstance(config_data, dict) or 'mcpServers' not in config_data:
        raise ValueError("Configuration must contain 'mcpServers' object")

    # 验证端口号唯一性
    ports = set()
    for service_id, service_config in config_data.get('mcpServers', {}).items():
        if 'out_port' in service_config:
            port = service_config['out_port']
            if port in ports:
                raise ValueError(f"Duplicate port number: {port}. Each service must have a unique out_port.")
            ports.add(port)

    # 备份原配置文件
    if os.path.exists(filepath):
        backup_file = f'{filepath}.backup.{int(time.time())}'
        try:
            import shutil
            shutil.copy2(filepath, backup_file)
        except Exception:
            pass  # 备份失败不影响保存

    # 保存新配置
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    return {"success": True, "message": "Configuration saved successfully"}

def get_config_template():
    """
    获取新配置的模板

    Returns:
        str: 配置模板的 JSON 字符串
    """
    template_config = {
        "mcpServers": {
            "new_service": {
                "name": "New MCP Service",
                "description": "Description of the new service",
                "command": "uv",
                "args": ["run", "script.py"],
                "cwd": "path/to/your/code",
                "out_port": 17001,
                "isActive": True
            }
        }
    }

    return json.dumps(template_config, indent=2, ensure_ascii=False)

def load_service_config(service_name, filepath='mcp_conf.json'):
    """
    加载单个服务的配置

    Args:
        service_name: 服务名称
        filepath: 配置文件路径

    Returns:
        dict: 包含服务ID和服务配置的字典

    Raises:
        FileNotFoundError: 配置文件不存在
        KeyError: 服务不存在
        Exception: 其他读取错误
    """
    # 如果主配置文件不存在，尝试使用示例文件
    if not os.path.exists(filepath):
        if os.path.exists('mcp_conf.example.json'):
            filepath = 'mcp_conf.example.json'
        else:
            raise FileNotFoundError(f"Configuration file not found: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        config_data = json.load(f)

    mcp_servers = config_data.get('mcpServers', {})

    # 查找服务：可能通过name字段或服务ID查找
    service_id = None
    service_config = None

    for sid, sconfig in mcp_servers.items():
        if sid == service_name or sconfig.get('name') == service_name:
            service_id = sid
            service_config = sconfig
            break

    if not service_config:
        raise KeyError(f"Service '{service_name}' not found in configuration")

    return {
        'service_id': service_id,
        'service_config': service_config,
        'full_config': config_data
    }

def save_service_config(service_name, service_config_content, filepath='mcp_conf.json'):
    """
    保存单个服务的配置

    Args:
        service_name: 服务名称
        service_config_content: 服务配置的JSON字符串
        filepath: 配置文件路径

    Returns:
        dict: 保存结果

    Raises:
        json.JSONDecodeError: JSON 格式错误
        ValueError: 配置结构错误
        Exception: 其他保存错误
    """
    # 验证服务配置 JSON 格式
    try:
        new_service_config = json.loads(service_config_content)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Invalid JSON format: {str(e)}", e.doc, e.pos)

    # 验证服务配置结构
    if 'out_port' not in new_service_config:
        raise ValueError("Service configuration must contain 'out_port' field")

    # 加载现有配置
    if not os.path.exists(filepath):
        if os.path.exists('mcp_conf.example.json'):
            filepath = 'mcp_conf.example.json'
        else:
            raise FileNotFoundError(f"Configuration file not found: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        config_data = json.load(f)

    # 查找服务ID
    service_id = None
    mcp_servers = config_data.get('mcpServers', {})

    for sid, sconfig in mcp_servers.items():
        if sid == service_name or sconfig.get('name') == service_name:
            service_id = sid
            break

    if not service_id:
        raise KeyError(f"Service '{service_name}' not found in configuration")

    # 验证新端口是否与现有服务冲突（除了自己）
    new_port = new_service_config['out_port']
    for sid, sconfig in mcp_servers.items():
        if sid != service_id and sconfig.get('out_port') == new_port:
            raise ValueError(f"Port {new_port} is already used by service '{sid}'")

    # 备份原配置文件
    backup_file = f'{filepath}.backup.{int(time.time())}'
    try:
        import shutil
        shutil.copy2(filepath, backup_file)
    except Exception:
        pass  # 备份失败不影响保存

    # 更新服务配置
    config_data['mcpServers'][service_id] = new_service_config

    # 保存配置
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    return {"success": True, "message": "Service configuration saved successfully"}

def delete_service_config(service_name, filepath='mcp_conf.json'):
    """ 
    """
    # 加载现有配置
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Configuration file not found: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        config_data = json.load(f)
    
    # 查找服务ID
    service_id = None
    mcp_servers = config_data.get('mcpServers', {})

    for sid, sconfig in mcp_servers.items():
        if sid == service_name or sconfig.get('name') == service_name:
            service_id = sid
            break

    if not service_id:
        raise KeyError(f"Service '{service_name}' not found in configuration")
    
    # 备份原配置文件
    backup_file = f'{filepath}.backup.{int(time.time())}'
    try:
        import shutil
        shutil.copy2(filepath, backup_file)
    except Exception:
        pass  # 备份失败不影响保存
    
    # 更新服务配置
    config_data['mcpServers'].pop(service_id)

    # 保存配置
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    return {"success": True, "message": "Service deleted."}

def main():
    lst_srv = load_conf()
    manager = ProcessManager(lst_srv)
    manager.start_all_enabled_services()
    try:
        while True:
            manager.refresh_svc_status()
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"Stopping...", flush=True)
        manager.stop_all_running_services()
        while True:
            n_alive = manager.count_alive()
            print(f"Alive proc = {n_alive}", flush=True)
            if n_alive>0:
                time.sleep(1)
            else:
                break
        #
        print("All MCP child processes have been closed, the main program has exited.")
        sys.exit(0)

if __name__ == '__main__':
    main()
