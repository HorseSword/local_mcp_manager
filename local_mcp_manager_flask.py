import multiprocessing as mp
import threading
import os
from flask import Flask, render_template, jsonify, request, g
from local_mcp_manager_core import ProcessManager, load_conf
import webbrowser
import sys
import time

app = Flask(__name__)

# 全局进程管理器实例
manager = None

def init_manager():
    global manager
    if manager is None:
        services = load_conf()
        manager = ProcessManager(services=services)

def get_manager():
    """获取进程管理器实例（使用 Flask 的应用上下文）"""
    if not hasattr(g, 'manager'):
        services = load_conf()
        g.manager = ProcessManager(services=services)
    return g.manager

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/services', methods=['GET'])
def get_services():
    """获取所有服务状态"""
    init_manager()
    manager.refresh_svc_status()
    
    services_data = []
    for svc in manager.services:
        services_data.append({
            'name': svc['name'],
            'out_type': svc['out_type'],
            'port': svc['port'],
            'is_enabled': svc['is_enabled'],
            'is_alive': svc['is_alive']
        })
    
    return jsonify({
        'success': True,
        'services': services_data
    })

@app.route('/api/services/start-all', methods=['POST'])
def start_all_services():
    """启动所有启用的服务"""
    init_manager()
    manager.start_all_enabled_services()
    manager.refresh_svc_status()
    
    return jsonify({
        'success': True,
        'message': '批量启动命令已执行'
    })

@app.route('/api/services/stop-all', methods=['POST'])
def stop_all_services():
    """停止所有运行中的服务"""
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
        'message': '所有服务已停止'
    })

@app.route('/api/services/<service_name>/start', methods=['POST'])
def start_service(service_name):
    """启动单个服务"""
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
            'message': f'服务 {service_name} 不存在'
        }), 404
    
    manager._start_service(service)
    manager.refresh_svc_status()
    
    return jsonify({
        'success': True,
        'message': f'服务 {service_name} 启动命令已执行'
    })

@app.route('/api/services/<service_name>/stop', methods=['POST'])
def stop_service(service_name):
    """停止单个服务"""
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
            'message': f'服务 {service_name} 不存在'
        }), 404
    
    manager._stop_service(service)
    manager.refresh_svc_status()
    
    return jsonify({
        'success': True,
        'message': f'服务 {service_name} 停止命令已执行'
    })

@app.route('/api/services/<service_name>/toggle', methods=['POST'])
def toggle_service_enabled(service_name):
    """切换服务的启用状态"""
    init_manager()
    
    # 找到对应服务
    for svc in manager.services:
        if svc['name'] == service_name:
            svc['is_enabled'] = not svc['is_enabled']
            return jsonify({
                'success': True,
                'message': f'服务 {service_name} 启用状态已切换',
                'is_enabled': svc['is_enabled']
            })
    
    return jsonify({
        'success': False,
        'message': f'服务 {service_name} 不存在'
    }), 404

def cleanup():
    """清理资源"""
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
    """延迟启动：打开浏览器并执行批量启动"""
    
    init_manager()
    manager.start_all_enabled_services()

    time.sleep(1.5)  # 等待服务器启动
    
    # 自动打开浏览器
    webbrowser.open('http://127.0.0.1:17000')
    
    # 等待页面加载后执行批量启动
    time.sleep(2)
    
    print("已自动执行批量启动")

if __name__ == "__main__":
    # Windows 下使用 multiprocessing 时需要保护入口
    mp.freeze_support()
    if os.name == "nt":
        mp.set_start_method("spawn", force=True)
    
    # 启动后台线程处理自动操作
    # startup_thread = threading.Thread(target=delayed_startup, daemon=True)
    # startup_thread.start()
    init_manager()
    manager.start_all_enabled_services()

    try:
        app.run(host='127.0.0.1', port=17000, debug=False)
    except KeyboardInterrupt:
        cleanup()
    finally:
        cleanup()
        sys.exit(0)