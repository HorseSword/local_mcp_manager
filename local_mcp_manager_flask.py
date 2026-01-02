"""
Docstring for local_mcp_manager_flask


"""

import multiprocessing as mp
import threading
import os
import json
from flask import Flask, render_template, jsonify, request, g, Response, stream_with_context
from local_mcp_manager_core import ProcessManager, load_conf, VERSION, load_config_raw, save_config_raw, get_config_template, load_service_config, save_service_config, delete_service_config
import webbrowser
import sys
import time
import asyncio

#%%
app = Flask(__name__)
task_queue = asyncio.Queue()
_background_task = None

# 全局进程管理器实例
manager = None

def init_manager():
    """ 
    对全局变量的 mamager 初始化。
    包括 load_conf 与 manager 初始化
    """
    global manager
    if manager is None:
        services = load_conf()
        manager = ProcessManager(services=services)
    return manager

def get_manager():
    """
    获取进程管理器实例（使用 Flask 的应用上下文）

    Get the process manager instance (using Flask's application context)    
    """
    if not hasattr(g, 'manager'):
        services = load_conf()
        g.manager = ProcessManager(services=services)
    return g.manager

@app.route('/')
async def index():
    init_manager()
    # asyncio.create_task(manager.get_tools_all())  # 无效
    return render_template('index.html')

@app.route('/api/aichat',methods=['GET'])
async def show_ai_chat():
    init_manager()
    return render_template('_mcp_chat.html')

@app.route('/api/services/<service_name>/info', methods=['GET'])
async def show_mcp_info(service_name):
    """
    Docstring for show_mcp_info
    获取 MCP 工具的信息。
    
    :param service_name: Description
    """
    init_manager()
    service_info = await manager.get_tools_by_name(service_name)
    dict_info = json.loads(service_info)
    template_params = {
        'serviceName' : service_name,
        'service_info' : service_info,
        'serviceTools' : json.dumps(dict_info['tools']),
        'servicePrompts' : json.dumps(dict_info['prompts']),
        'serviceResources' : json.dumps(dict_info['resources']),
        'n_tools': len(dict_info['tools']),
        'n_prompts': len(dict_info['prompts']),
        'n_resources': len(dict_info['resources']),
    }

    return render_template(
        '_mcp_info.html', 
        **template_params
    )

@app.route('/api/all', methods=['GET'])
async def mcp_get_all():
    """ 
    这个可以强制启动所有服务并刷新MCP缓存。
    """
    init_manager()
    service_all = await manager.get_tools_all()
    return service_all

@app.route('/api/services/<service_name>/delete', methods=['POST'])
async def mcp_delete(service_name):
    """ 
    delete service
    """
    try:
        res = delete_service_config(service_name)
        return jsonify({
            'success': True,
            'result': res
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Delete failed: {str(e)}'
        }), 500

@app.route('/api/services/<service_name>/call_tool', methods=['POST'])
async def mcp_call_tool(service_name):
    """
    调用指定的工具。

    重要参数：
    - tool_name: str
    - parameters: object。
    """
    
    try:
        # 获取请求数据
        data = request.get_json()
        print(f"【mcp_call_tool】{data}")
        if not data:
            return jsonify({
                'success': False,
                'error': 'No JSON data provided'
            }), 400

        tool_name = data.get('tool_name')
        parameters = data.get('parameters', {})

        if not tool_name:
            return jsonify({
                'success': False,
                'error': 'Tool name is required'
            }), 400

        # 初始化管理器
        init_manager()

        # 调用工具
        tool_result_json = await manager.call_tool(service_name, tool_name, json.dumps(parameters))

        # 解析结果
        tool_result = json.loads(tool_result_json)

        return jsonify({
            'success': True,
            'result': tool_result
        })

    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid JSON in parameters: {str(e)}'
        }), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Tool call failed: {str(e)}'
        }), 500

@app.route('/api/services/<service_name>/ai_chat_stream', methods=['POST'])
async def mcp_ai_chat_stream(service_name):
    """
    AI聊天流式接口 - 使用SSE增量返回工具调用结果
    """
    try:
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No JSON data provided'
            }), 400

        lst_msg = data.get('messages')

        if not lst_msg:
            return jsonify({
                'success': False,
                'error': 'Message is required'
            }), 400

        # 初始化管理器
        init_manager()

        # 使用队列在线程间传递数据
        import queue
        result_queue = queue.Queue()

        # 在线程中运行异步生成器
        async def run_stream():
            try:
                async for chunk in manager.ai_chat_stream(service_name, lst_msg):
                    result_queue.put(chunk)
                # 发送完成信号
                result_queue.put(None)
            except Exception as e:
                error_msg = json.dumps({
                    'type': 'error',
                    'message': f'Stream error: {str(e)}'
                }, ensure_ascii=False)
                result_queue.put(error_msg)
                result_queue.put(None)

        # 在新线程中运行
        import threading
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(run_stream())
            finally:
                loop.close()

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

        # 定义同步生成器
        def generate():
            try:
                while True:
                    chunk = result_queue.get()
                    if chunk is None:  # 完成信号
                        break
                    # SSE 格式: data: <json>\n\n
                    yield f"data: {chunk}\n\n"
            except GeneratorExit:
                pass
            except Exception as e:
                error_msg = json.dumps({
                    'type': 'error',
                    'message': f'Generator error: {str(e)}'
                }, ensure_ascii=False)
                yield f"data: {error_msg}\n\n"

        # 返回 SSE 流
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'AI chat stream failed: {str(e)}'
        }), 500

@app.route('/api/config/edit')
def edit_config():
    """
    编辑配置文件页面
    """
    try:
        config_content = load_config_raw()
        return render_template('_mcp_edit_unified.html',
                             edit_type='config',
                             mode='Edit',
                             config_content=config_content)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to load configuration: {str(e)}'
        }), 500

@app.route('/api/config/add')
def add_config():
    """
    添加新配置页面
    """
    try:
        # 找到下一个可用的端口
        current_config = load_config_raw()
        used_ports = []

        import json
        try:
            config_data = json.loads(current_config)
            if 'mcpServers' in config_data:
                for service_data in config_data['mcpServers'].values():
                    if 'out_port' in service_data:
                        used_ports.append(service_data['out_port'])
        except (json.JSONDecodeError, KeyError):
            pass

        # 找到下一个可用端口（从17001开始）
        next_port = 17001
        while next_port in used_ports:
            next_port += 1

        # 创建新服务模板（只包含单个服务配置）
        new_service_config = {
            "name": "New Service",
            "description": "Service description",
            "command": "python",
            "args": ["script.py"],
            "cwd": "",
            "out_port": next_port,
            "is_enabled": True,
            "env": {},
            "type": "stdio",
            "url": "",
            "headers": {},
            "host": "127.0.0.1"
        }

        config_content = json.dumps(new_service_config, indent=2, ensure_ascii=False)

        return render_template('_mcp_edit_unified.html',
                             edit_type='add_service',
                             mode='Add',
                             config_content=config_content)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to load configuration for adding service: {str(e)}'
        }), 500

@app.route('/api/config/save', methods=['POST'])
def save_config():
    """
    保存配置文件
    """
    try:
        config_content = request.get_data(as_text=True)

        if not config_content:
            return jsonify({
                'success': False,
                'error': 'No configuration content provided'
            }), 400

        save_config_raw(config_content)

        return jsonify({
            'success': True,
            'message': 'Configuration saved successfully'
        })

    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid JSON format: {str(e)}'
        }), 400

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to save configuration: {str(e)}'
        }), 500

@app.route('/api/config/add-service', methods=['POST'])
def add_service_to_config():
    """
    添加新服务到现有配置
    """
    try:
        service_config_content = request.get_data(as_text=True)

        if not service_config_content:
            return jsonify({
                'success': False,
                'error': 'No service configuration provided'
            }), 400

        # 解析新服务配置
        new_service_config = json.loads(service_config_content)

        # 验证必需字段
        if 'out_port' not in new_service_config:
            return jsonify({
                'success': False,
                'error': 'Missing required field: out_port'
            }), 400

        # 生成服务ID（如果name字段存在且有效，则用作ID；否则使用默认值）
        service_name = new_service_config.get('name', 'new_service').replace(' ', '_').lower()
        if not service_name or service_name == 'new_service':
            # 如果没有有效名称，使用时间戳生成唯一ID
            import time
            service_name = f"service_{int(time.time())}"

        # 加载现有配置
        current_config = load_config_raw()
        try:
            config_data = json.loads(current_config) if current_config.strip() else {"mcpServers": {}}
        except json.JSONDecodeError:
            config_data = {"mcpServers": {}}

        # 确保mcpServers存在
        if 'mcpServers' not in config_data:
            config_data['mcpServers'] = {}

        # 检查服务ID冲突
        if service_name in config_data['mcpServers']:
            return jsonify({
                'success': False,
                'error': f'Service ID "{service_name}" already exists. Please change the service name.'
            }), 400

        # 检查端口冲突
        new_port = new_service_config['out_port']
        for existing_service in config_data['mcpServers'].values():
            if existing_service.get('out_port') == new_port:
                return jsonify({
                    'success': False,
                    'error': f'Port {new_port} is already in use by another service.'
                }), 400

        # 添加新服务到配置
        config_data['mcpServers'][service_name] = new_service_config

        # 保存完整配置
        updated_config_content = json.dumps(config_data, indent=2, ensure_ascii=False)
        save_config_raw(updated_config_content)

        return jsonify({
            'success': True,
            'message': f'Service "{service_name}" added successfully'
        })

    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid JSON format: {str(e)}'
        }), 400

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to add new service: {str(e)}'
        }), 500

@app.route('/api/services/<service_name>/edit')
def edit_service(service_name):
    """
    编辑单个服务的配置
    """
    try:
        service_data = load_service_config(service_name)
        service_config_json = json.dumps(service_data['service_config'], indent=2, ensure_ascii=False)

        return render_template('_mcp_edit_unified.html',
                             edit_type='service',
                             service_name=service_name,
                             service_id=service_data['service_id'],
                             config_content=service_config_json)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to load service configuration: {str(e)}'
        }), 500

@app.route('/api/services/<service_name>/save', methods=['POST'])
def save_service(service_name):
    """
    保存单个服务的配置
    """
    try:
        service_config_content = request.get_data(as_text=True)

        if not service_config_content:
            return jsonify({
                'success': False,
                'error': 'No service configuration content provided'
            }), 400

        save_service_config(service_name, service_config_content)

        return jsonify({
            'success': True,
            'message': 'Service configuration saved successfully'
        })

    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid JSON format: {str(e)}'
        }), 400

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to save service configuration: {str(e)}'
        }), 500

#%%

@app.route('/api/services', methods=['GET'])
async def get_services():
    """
    获取服务状态

    get status
    """
    init_manager()
    manager.refresh_svc_status()
    for svc in manager.services:
        await manager.check_mcp_status(svc)  # 刷新MCP服务状态，重要

    services_data = []
    for svc in manager.services:
        services_data.append({
            'name': svc['name'],
            'in_type': svc.get("in_type","null"),
            'out_type': svc['out_type'],
            'port': svc['port'],
            'is_enabled': svc['is_enabled'],
            'is_alive': svc['is_alive'],
            'mcp_status': svc.get('mcp_status','UNKNOWN'),
        })
    
    return jsonify({
        'success': True,
        'services': services_data
    })

@app.route('/api/services/start-all', methods=['POST'])
async def start_all_services():
    """
    启动所有启用的服务
    
    """
    init_manager()
    manager.start_all_enabled_services()
    manager.refresh_svc_status()

    return jsonify({
        'success': True,
        'message': 'Batch startup command has been executed.'
    })

@app.route('/api/services/stop-all', methods=['POST'])
def stop_all_services():
    """
    停止所有运行中的服务
    """
    init_manager()
    manager.stop_all_running_services()
    
    # 等待所有进程停止
    import time
    while True:
        n_alive = manager.count_alive()
        if n_alive > 0:
            time.sleep(0.5)
        else:
            break
    
    return jsonify({
        'success': True,
        'message': 'All services stopped.'
    })

@app.route('/api/services/reboot', methods=['POST'])
def reboot():
    """ 
    重启服务
    """
    stop_all_services()
    manager.reload_conf()
    manager.start_all_enabled_services()
    return jsonify({
        'success': True,
        'message': 'Reboot successfully.'
    })


@app.route('/api/services/<service_name>/start', methods=['POST'])
def start_service(service_name):
    """
    启动服务

    Start one service
    """
    init_manager()
    
    # 找到对应服务
    service = None
    for svc in manager.services:
        if svc['name'] == service_name:
            service = svc
            break
    
    if not service:
        return jsonify({
            'success': False,
            'message': f'Service {service_name} does not exist.'
        }), 404
    
    manager._start_service(service)
    manager.refresh_svc_status()
    
    return jsonify({
        'success': True,
        'message': f'Service {service_name} started.'
    })

@app.route('/api/services/<service_name>/stop', methods=['POST'])
def stop_service(service_name):
    """
    停止单个服务
    
    Stop one service
    """
    init_manager()
    
    # 找到对应服务
    service = None
    for svc in manager.services:
        if svc['name'] == service_name:
            service = svc
            break
    
    if not service:
        return jsonify({
            'success': False,
            'message': f'Service {service_name} does not exist.'
        }), 404
    
    manager._stop_service(service)
    manager.refresh_svc_status()
    
    return jsonify({
        'success': True,
        'message': f'Service {service_name} stopped.'
    })

@app.route('/api/services/<service_name>/toggle', methods=['POST'])
def toggle_service_enabled(service_name):
    """
    切换服务的启用状态
    
    Toggle service
    """
    init_manager()
    
    # 找到对应服务
    for svc in manager.services:
        if svc['name'] == service_name:
            #
            if True:  # 同步操作后台服务
                if svc['is_enabled']:
                    stop_service(service_name)
                else:
                    start_service(service_name)
            #
            # svc['is_enabled'] = not svc['is_enabled']
            return jsonify({
                'success': True,
                'message': f'Service {service_name} status switched.',
                'is_enabled': svc['is_enabled']
            })
    
    return jsonify({
        'success': False,
        'message': f'Service {service_name} does not exist.'
    }), 404

@app.route('/api/settings')
def show_settings():
    """
    显示设置页面

    Show settings page
    """
    return render_template('_settings.html')

@app.route('/api/settings/load', methods=['GET'])
def load_settings():
    """
    加载设置文件

    Load settings from settings.json
    """
    try:
        # settings_file = os.path.join(os.path.dirname(__file__), 'settings.json')

        # # 如果文件不存在，返回默认设置
        # if not os.path.exists(settings_file):
        #     default_settings = {
        #         'openai_url': '',
        #         'openai_key': '',
        #         'openai_model': ''
        #     }
        #     return jsonify({
        #         'success': True,
        #         'settings': default_settings
        #     })

        # # 读取现有设置
        # with open(settings_file, 'r', encoding='utf-8') as f:
        #     settings = json.load(f)

        settings = manager.basic_config.cfg
        return jsonify({
            'success': True,
            'settings': settings
        })

    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid JSON format in settings.json: {str(e)}'
        }), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to load settings: {str(e)}'
        }), 500

@app.route('/api/settings/save', methods=['POST'])
def save_settings():
    """
    保存设置到文件

    Save settings to settings.json
    """
    try:
        settings = request.get_json()

        # 验证数据
        if not isinstance(settings, dict):
            return jsonify({
                'success': False,
                'error': 'Invalid settings format'
            }), 400

        # 保存到文件
        # settings_file = os.path.join(os.path.dirname(__file__), 'settings.json')
        # with open(settings_file, 'w+', encoding='utf-8') as f:
        #     json.dump(settings, f, indent=2, ensure_ascii=False)
        manager.basic_config.cfg.update(settings)
        manager.basic_config.save_cfg()

        return jsonify({
            'success': True,
            'message': 'Settings saved successfully'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to save settings: {str(e)}'
        }), 500

def cleanup():
    """
    清理资源
    """
    global manager
    if manager:
        print("正在停止所有服务...")
        manager.stop_all_running_services()
        
        while True:
            n_alive = manager.count_alive()
            if n_alive > 0:
                time.sleep(0.5)
            else:
                break
        print("所有服务已停止")

def delayed_startup():
    """
    延迟启动：打开浏览器并执行批量启动

    Not used for now.
    """
    
    init_manager()
    manager.start_all_enabled_services()

    time.sleep(1.5)  # 等待服务器启动
    
    # 自动打开浏览器
    try:
        webbrowser.open('http://127.0.0.1:17000')

        # 等待页面加载后执行批量启动
        time.sleep(2)
    except:
        pass
    
    print("已自动执行批量启动")

if __name__ == "__main__":
    # 
    # 启动参数
    import argparse
    parser = argparse.ArgumentParser(description="Local MCP Manager")
    parser.add_argument("--host", default='127.0.0.1', help="Server IP")
    parser.add_argument("--port", default=17000, help="WebUI Port Number")
    args = parser.parse_args()
    #
    flask_host = args.host # '127.0.0.1'
    flask_port = args.port # 17000
    #
    # Windows 下使用 multiprocessing 时需要保护入口
    mp.freeze_support()
    if os.name == "nt":
        mp.set_start_method("spawn", force=True)
    #
    # 启动后台线程处理自动操作
    # startup_thread = threading.Thread(target=delayed_startup, daemon=True)
    # startup_thread.start()
    #
    manager = init_manager()
    manager.start_all_enabled_services()
    #
    try:
        app.run(host = flask_host, port = flask_port, debug = False)
    except KeyboardInterrupt:
        cleanup()
    finally:
        cleanup()
        sys.exit(0)
