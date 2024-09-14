import socket
import json
import threading
import time
import random
import argparse
import logging
import sys
import asyncio
from asyncio import Lock


console_lock = threading.Lock()

def cli_thread(server):
    try:
        while True:
            with console_lock:
                command = input("Enter command (reconnect/stop): ").strip().lower()
            if command == "reconnect":
                with console_lock:
                    new_host = input("Enter new host: ")
                    new_port = int(input("Enter new port: "))
                asyncio.run_coroutine_threadsafe(
                    server.send_reconnect(new_host, new_port),
                    server.loop
                )
                with console_lock:
                    print(f"Reconnect command sent to {new_host}:{new_port}", flush=True)
            elif command == "stop":
                server.stop()
                break
            else:
                with console_lock:
                    print("Unknown command", flush=True)
    except KeyboardInterrupt:
        with console_lock:
            logging.info("Received keyboard interrupt, stopping server")
        server.stop()

class MockStratumV1Server:
    def __init__(self, host='0.0.0.0', port=3333, difficulty=1, work_interval=30):
        self.host = host
        self.port = port
        self.difficulty = difficulty
        self.extranonce1 = '00000000'
        self.extranonce2_size = 4
        self.work_interval = work_interval
        self.running = True
        self.clients = []
        self.clients_lock = Lock()
        self.job_id = 0

        # key -> writer, values {'difficulty': diff}
        self.client_info = {}
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def start(self):
        self.loop.run_until_complete(self.main_async())

    async def main_async(self):
        # Start the periodic work update coroutine as a task
        asyncio.create_task(self.periodic_work_update())
        # Start the server
        await self.start_server()

    async def start_server(self):
        server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        addr = server.sockets[0].getsockname()
        logging.info(f"Serving on {addr}")
        async with server:
            await server.serve_forever()

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        async with self.clients_lock:
            self.clients.append(writer)
        logging.info(f"Client connected: {addr}")

        try:
            while self.running:
                data = await reader.readline()
                if not data:
                    break
                message = json.loads(data.decode())
                await self.handle_message(writer, message)
        except Exception as e:
            logging.error(f"Error handling client {addr}: {e}")
        finally:
            async with self.clients_lock:
                # need to remove the client
                if writer in self.clients:
                    self.clients.remove(writer)

                # cleanup the client info
                if writer in self.client_info:
                    del self.client_info[writer]
            
            writer.close()
            await writer.wait_closed()
            logging.info(f"Client disconnected: {addr}")

    async def handle_message(self, writer, message):
        method = message.get('method')
        if method == 'mining.subscribe':
            await self.handle_subscribe(writer, message)
        elif method == 'mining.authorize':
            await self.handle_authorize(writer, message)
        elif method == 'mining.submit':
            await self.handle_submit(writer, message)
        elif method == 'mining.configure':
            await self.handle_configure(writer, message)
        elif method == 'mining.suggest_difficulty':
            await self.handle_suggest_difficulty(writer, message)
        else:
            logging.warning(f"Unknown method: {method}")

    async def handle_suggest_difficulty(self, writer, message):
        params = message.get('params', [])
        if params:
            suggested_difficulty = params[0]
            # Update the client's difficulty setting
            client_info = self.client_info.get(writer, {})
            client_info['difficulty'] = suggested_difficulty
            self.client_info[writer] = client_info
            logging.info(f"Client suggested difficulty: {suggested_difficulty}")
            await self.send_difficulty(writer, suggested_difficulty)
        else:
            logging.warning("No difficulty provided in 'mining.suggest_difficulty'")
        # Respond with 'null' result as per JSON-RPC 2.0 specification
        response = {
            "id": message['id'],
            "result": None,
            "error": None
        }
        await self.send_message(writer, response)

    async def handle_subscribe(self, writer, message):
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
        await self.send_message(writer, response)

    async def handle_authorize(self, writer, message):
        response = {
            "id": message['id'],
            "result": True,
            "error": None
        }
        await self.send_message(writer, response)
        await self.send_difficulty(writer)
        await self.send_work(writer)

    async def handle_submit(self, writer, message):
        share_valid = random.choice([True, False])
        response = {
            "id": message['id'],
            "result": share_valid,
            "error": None if share_valid else [21, "Invalid share", None]
        }
        await self.send_message(writer, response)
        if share_valid:
            logging.info(f"Accepted share from client")
        else:
            logging.warning(f"Rejected share from client")

    async def handle_configure(self, writer, message):
        response = {
            "id": message['id'],
            "result": {"version-rolling": True},
            "error": None
        }
        await self.send_message(writer, response)

    async def send_message(self, writer, message):
        try:
            writer.write(json.dumps(message).encode() + b'\n')
            await writer.drain()
        except Exception as e:
            logging.error(f"Error sending message to client: {e}")
            async with self.clients_lock:
                if writer in self.clients:
                    self.clients.remove(writer)

    async def send_difficulty(self, writer, difficulty=None):
        if difficulty is None:
            difficulty = self.difficulty
        message = {
            "id": None,
            "method": "mining.set_difficulty",
            "params": [difficulty]
        }
        await self.send_message(writer, message)


    async def send_work(self, writer):
        self.job_id += 1
        ntime = f"{int(time.time()):08x}"

        # todo if we want to use dif in work assignment
        # client_info = self.client_info.get(writer, {})
        # difficulty = client_info.get('difficulty', self.difficulty)

        message = {
            "id": None,
            "method": "mining.notify",
            "params": [
                f"{self.job_id:04x}",
                "0" * 64,  # prev_block_hash
                "0" * 128,  # coinbase1
                "0" * 128,  # coinbase2
                [],         # merkle_branch
                "00000002", # version
                "1a1dc0de", # nbits
                ntime,
                False       # clean_jobs
            ]
        }
        await self.send_message(writer, message)

    async def periodic_work_update(self):
        while self.running:
            await asyncio.sleep(self.work_interval)
            async with self.clients_lock:
                clients_copy = list(self.clients)
            for writer in clients_copy:
                await self.send_work(writer)
            logging.info(f"Sent work update to {len(clients_copy)} clients")

    async def send_reconnect(self, new_host, new_port, wait_time=10):
        message = {
            "id": None,
            "method": "client.reconnect",
            "params": [new_host, new_port, wait_time]
        }
        async with self.clients_lock:
            clients_copy = list(self.clients)
        for writer in clients_copy:
            await self.send_message(writer, message)
        logging.info(f"Sent reconnect message to all clients: {new_host}:{new_port}")

    def stop(self):
        self.running = False
        # Stop the event loop
        self.loop.stop()

def main():
    parser = argparse.ArgumentParser(description="Mock Stratum V1 Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=3333, help="Port to listen on")
    parser.add_argument("--difficulty", type=float, default=1, help="Initial mining difficulty")
    parser.add_argument("--work-interval", type=int, default=30, help="Interval between work updates (seconds)")
    parser.add_argument("--log-level", default="INFO", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help="Set the logging level")
    args = parser.parse_args()

    # Adjust logging configuration
    logging.basicConfig(
        level=args.log_level,
        format='%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s',
        datefmt='%H:%M:%S'
    )

    server = MockStratumV1Server(args.host, args.port, args.difficulty, args.work_interval)

    # Start the server thread
    server_thread = threading.Thread(target=server.start, name='ServerThread', daemon=True)
    server_thread.start()

    # Start the CLI thread
    cli_thread_instance = threading.Thread(target=cli_thread, args=(server,), name='CLIThread')
    cli_thread_instance.start()

    # Wait for the CLI thread to finish
    cli_thread_instance.join()
    server_thread.join()

if __name__ == "__main__":
    main()
