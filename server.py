import socket
import json
import threading
import time
import random
import argparse
import logging
import sys

class MockStratumV1Server:
    def __init__(self, host='0.0.0.0', port=3333, difficulty=1, work_interval=30):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.clients = []
        self.job_id = 0
        self.difficulty = difficulty
        self.extranonce1 = '00000000'
        self.extranonce2_size = 4
        self.work_interval = work_interval
        self.running = True

    def start(self):
        self.sock.listen(5)
        logging.info(f"Mock Stratum V1 server listening on {self.host}:{self.port}")
        
        # Start the work update thread
        work_thread = threading.Thread(target=self.periodic_work_update)
        work_thread.start()

        while self.running:
            try:
                client, addr = self.sock.accept()
                logging.info(f"New connection from {addr}")
                client_thread = threading.Thread(target=self.handle_client, args=(client,))
                client_thread.start()
            except Exception as e:
                logging.error(f"Error accepting connection: {e}")

    def handle_client(self, client):
        self.clients.append(client)
        while self.running:
            try:
                data = client.recv(1024).decode('utf-8')
                if not data:
                    break
                messages = data.split('\n')
                for message in messages:
                    if message:
                        self.handle_message(client, json.loads(message))
            except json.JSONDecodeError:
                logging.warning(f"Received invalid JSON: {data}")
            except Exception as e:
                logging.error(f"Error handling client: {e}")
                break
        client.close()
        self.clients.remove(client)

    def handle_message(self, client, message):
        method = message.get('method')
        if method == 'mining.subscribe':
            self.handle_subscribe(client, message)
        elif method == 'mining.authorize':
            self.handle_authorize(client, message)
        elif method == 'mining.submit':
            self.handle_submit(client, message)
        else:
            logging.warning(f"Received unknown method: {method}")

    def handle_subscribe(self, client, message):
        response = {
            "id": message['id'],
            "result": [
                [
                    ["mining.set_difficulty", "1"],
                    ["mining.notify", "1"]
                ],
                self.extranonce1,
                self.extranonce2_size
            ],
            "error": None
        }
        self.send_message(client, response)

    def handle_authorize(self, client, message):
        response = {
            "id": message['id'],
            "result": True,
            "error": None
        }
        self.send_message(client, response)
        self.send_difficulty(client)
        self.send_work(client)

    def handle_submit(self, client, message):
        # In a real implementation, you'd validate the submitted work here
        response = {
            "id": message['id'],
            "result": True,
            "error": None
        }
        self.send_message(client, response)
        logging.info(f"Received work submission: {message}")

    def send_message(self, client, message):
        try:
            client.send(json.dumps(message).encode() + b'\n')
        except Exception as e:
            logging.error(f"Error sending message to client: {e}")
            self.clients.remove(client)

    def send_difficulty(self, client):
        message = {
            "id": None,
            "method": "mining.set_difficulty",
            "params": [self.difficulty]
        }
        self.send_message(client, message)

    def send_work(self, client):
        self.job_id += 1
        message = {
            "id": None,
            "method": "mining.notify",
            "params": [
                f"{self.job_id:04x}",
                "0" * 64,  # prev_block_hash
                "01000000" + "0" * 96,  # coinbase_1
                "0" * 96,  # coinbase_2
                [],  # merkle_branch
                "00000002",  # version
                "1A015F53",  # nbits (difficulty target)
                f"{int(time.time()):08x}",  # ntime
                False  # clean_jobs
            ]
        }
        self.send_message(client, message)

    def send_reconnect(self, new_host, new_port, wait_time=10):
        message = {
            "id": None,
            "method": "client.reconnect",
            "params": [new_host, new_port, wait_time]
        }
        for client in self.clients:
            self.send_message(client, message)
        logging.info(f"Sent reconnect message to all clients: {new_host}:{new_port}")

    def periodic_work_update(self):
        while self.running:
            time.sleep(self.work_interval)
            for client in self.clients:
                self.send_work(client)
            logging.info(f"Sent work update to {len(self.clients)} clients")

    def stop(self):
        self.running = False
        self.sock.close()

def main():
    parser = argparse.ArgumentParser(description="Mock Stratum V1 Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=3333, help="Port to listen on")
    parser.add_argument("--difficulty", type=float, default=1, help="Initial mining difficulty")
    parser.add_argument("--work-interval", type=int, default=30, help="Interval between work updates (seconds)")
    parser.add_argument("--log-level", default="INFO", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help="Set the logging level")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format='%(asctime)s - %(levelname)s - %(message)s')

    server = MockStratumV1Server(args.host, args.port, args.difficulty, args.work_interval)
    server_thread = threading.Thread(target=server.start)
    server_thread.start()

    try:
        while True:
            command = input("Enter command (reconnect/stop): ").strip().lower()
            if command == "reconnect":
                new_host = input("Enter new host: ")
                new_port = int(input("Enter new port: "))
                server.send_reconnect(new_host, new_port)
            elif command == "stop":
                server.stop()
                break
            else:
                print("Unknown command")
    except KeyboardInterrupt:
        logging.info("Received keyboard interrupt, stopping server")
        server.stop()

    server_thread.join()

if __name__ == "__main__":
    main()