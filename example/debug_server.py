import socket
import time
import signal
import sys

HOST = "127.0.0.1"
PORT = 8234


def main():
    def signal_handler(sig, frame):
        print("Closing socket")
        s.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        print(f"Listening on {HOST}:{PORT}")
        while True:
            conn, addr = s.accept()
            with conn:
                print(f"Connected by {addr}")
                try:
                    while True:
                        conn.sendall(b"\x10\x05\x01")
                        data = conn.recv(1024)
                        if not data:
                            break
                        print("Received", data)
                        time.sleep(10)  # Add a delay to avoid overwhelming the network
                except ConnectionResetError:
                    print(f"Connection reset by {addr}")
                    continue
    s.close()


if __name__ == "__main__":
    main()
