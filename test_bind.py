import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(('0.0.0.0', 5001))
    print("Binding successful. Port 5001 is FREE.")
except Exception as e:
    print(f"Binding failed: {e}")
finally:
    s.close()