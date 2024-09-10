# Stratum V1 Mock Server

This is a mock of a Stratum V1 mining pool server for testing purposes.

## Features

- Simulates some basic Stratum V1 protocol 

## Usage

```
python3 server.py [--host HOST] [--port PORT] [--difficulty DIFFICULTY] [--work-interval WORK_INTERVAL] [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}]
```

## Commands

While the server is running, you can use the following commands:

- `reconnect`: Send a reconnect command to all clients
- `stop`: Stop the server

#### TODO add more commands 
