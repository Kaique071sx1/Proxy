import socket
import threading
import select
import os
import requests
import time
from flask import Flask, jsonify
from pyngrok import ngrok, conf

# --- Configurações ---
PROXY_HOST = '0.0.0.0'
PROXY_PORT = int(os.getenv('ROOT_PORT', 9090))
PROXY_USER = os.getenv('USER', 'user')
PROXY_PASS = os.getenv('PASS', 'pass')
NGROK_TOKEN = os.getenv('NGROK_TOKEN')

app = Flask(__name__)

# --- API IP ---
@app.route('/ip', methods=['GET'])
def get_ip():
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get('https://api.ipify.org?format=json', headers=headers, timeout=10)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
def health_check():
    return "Proxy Online", 200

# --- PROXY SOCKS5 ---
def handle_client(client_socket):
    try:
        header = client_socket.recv(2)
        if not header: return
        version, nmethods = header
        if version != 5: return
        client_socket.recv(nmethods)
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
        
        port = int.from_bytes(client_socket.recv(2), 'big')

        try:
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.connect((addr, port))
            bind_addr = remote.getsockname()
            addr_ip = int.from_bytes(socket.inet_aton(bind_addr[0]), 'big')
            port_bytes = bind_addr[1].to_bytes(2, 'big')
            client_socket.sendall(b'\x05\x00\x00\x01' + addr_ip.to_bytes(4, 'big') + port_bytes)
        except:
            client_socket.sendall(b'\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00')
            client_socket.close()
            return

        while True:
            r, _, _ = select.select([client_socket, remote], [], [])
            if client_socket in r:
                data = client_socket.recv(4096)
                if not data: break
                remote.sendall(data)
            if remote in r:
                data = remote.recv(4096)
                if not data: break
                client_socket.sendall(data)
        
        client_socket.close()
        remote.close()
    except:
        if client_socket: client_socket.close()

def start_proxy_server():
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((PROXY_HOST, PROXY_PORT))
        server.listen(5)
        print(f"[*] Proxy SOCKS5 rodando na porta interna {PROXY_PORT}", flush=True)
        while True:
            client, _ = server.accept()
            threading.Thread(target=handle_client, args=(client,)).start()
    except Exception as e:
        print(f"[!] Erro ao iniciar Proxy: {e}", flush=True)

# --- CONFIGURAÇÃO NGROK ---
def start_ngrok():
    print("[*] Iniciando Ngrok...", flush=True)
    if not NGROK_TOKEN:
        print("[!] ERRO: NGROK_TOKEN nao encontrado nas variaveis de ambiente!", flush=True)
        return

    try:
        # Define o token explicitamente
        ngrok.set_auth_token(NGROK_TOKEN)
        
        # Cria o túnel TCP
        url = ngrok.connect(PROXY_PORT, "tcp")
        
        print("\n==========================================", flush=True)
        print(f"SUCESSO! PROXY DISPONIVEL EM: {url.public_url}", flush=True)
        print("Use o endereco acima (sem 'tcp://') no seu app.", flush=True)
        print("==========================================\n", flush=True)
        
    except Exception as e:
        print(f"[!] ERRO CRITICO NGROK: {e}", flush=True)

if __name__ == '__main__':
    # Inicia Threads
    t_proxy = threading.Thread(target=start_proxy_server)
    t_proxy.daemon = True
    t_proxy.start()

    t_ngrok = threading.Thread(target=start_ngrok)
    t_ngrok.daemon = True
    t_ngrok.start()
    
    # Inicia Flask
    port = int(os.environ.get("PORT", 10000))
    print(f"[*] Iniciando Webserver na porta {port}", flush=True)
    app.run(host='0.0.0.0', port=port)
