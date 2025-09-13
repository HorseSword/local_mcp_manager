import multiprocessing as mp
import os
import json
import time
import signal
import sys
from fastmcp import FastMCP
from fastmcp import Client
from fastmcp.server.proxy import ProxyClient

#
VERSION = 'v0.1.2' # 2025-9-13
# VERSION = 'v0.1.1' # 2025-9-11
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


def load_conf(filepath = 'mcp_conf.json'):
    lst_mprocesses = []
    #
    with open(filepath,'r',encoding='utf8') as f:
        dict_conf = json.load(f)
    #
    mcp_servers = dict_conf.get("mcpServers")
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
