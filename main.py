import socket
import threading
import select
import os
import requests
from flask import Flask, jsonify

PROXY_HOST = '0.0.0.0'
PROXY_PORT = int(os.getenv('ROOT_PORT', 9090))
PROXY_USER = os.getenv('USER', 'user')
PROXY_PASS = os.getenv('PASS', 'pass')

app = Flask(__name__)

@app.route('/ip', methods=['GET'])
def get_ip():
    try:
        response = requests.get('https://ifconfig.co/json')
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
def health_check():
    return "Online", 200

def handle_client(client_socket):
    try:
        header = client_socket.recv(2)
        if not header: return
        version, nmethods = header
        
        if version != 5: return

        methods = client_socket.recv(nmethods)
        
        if 2 not in methods:
            client_socket.close()
            return

        client_socket.sendall(b'\x05\x02')

        auth_header = client_socket.recv(2)
        auth_ver, ulen = auth_header
        username = client_socket.recv(ulen).decode()
        plen = client_socket.recv(1)[0]
        password = client_socket.recv(plen).decode()

        if username == PROXY_USER and password == PROXY_PASS:
            client_socket.sendall(b'\x01\x00')
        else:
            client_socket.sendall(b'\x01\x01')
            client_socket.close()
            return

        request = client_socket.recv(4)
        ver, cmd, rsv, atyp = request

        if cmd != 1:
            client_socket.close()
            return

        if atyp == 1:
            addr = socket.inet_ntoa(client_socket.recv(4))
        elif atyp == 3:
            domain_len = client_socket.recv(1)[0]
            addr = client_socket.recv(domain_len).decode()
        elif atyp == 4:
            addr = socket.inet_ntop(socket.AF_INET6, client_socket.recv(16))
        else:
            client_socket.close()
            return

        port = int.from_bytes(client_socket.recv(2), 'big')

        try:
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.connect((addr, port))
            bind_addr = remote.getsockname()
            addr_ip = int.from_bytes(socket.inet_aton(bind_addr[0]), 'big')
            port_bytes = bind_addr[1].to_bytes(2, 'big')
            client_socket.sendall(b'\x05\x00\x00\x01' + addr_ip.to_bytes(4, 'big') + port_bytes)
        except Exception:
            client_socket.sendall(b'\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00')
            client_socket.close()
            return

        while True:
            r, _, _ = select.select([client_socket, remote], [], [])
            if client_socket in r:
                data = client_socket.recv(4096)
                if len(data) <= 0: break
                remote.sendall(data)
            if remote in r:
                data = remote.recv(4096)
                if len(data) <= 0: break
                client_socket.sendall(data)

        client_socket.close()
        remote.close()

    except Exception:
        if client_socket: client_socket.close()

def start_proxy_server():
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((PROXY_HOST, PROXY_PORT))
        server.listen(5)
        while True:
            client_socket, _ = server.accept()
            client_thread = threading.Thread(target=handle_client, args=(client_socket,))
            client_thread.start()
    except Exception as e:
        print(f"Proxy Error: {e}")

if __name__ == '__main__':
    proxy_thread = threading.Thread(target=start_proxy_server)
    proxy_thread.daemon = True
    proxy_thread.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
