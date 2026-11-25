"""Reproduce the B incident with the real traci code (identical in 1.25 and 1.28 for connect/init/start).

When SUMO cannot bind its port (Address already in use) and the port lies in the client's ephemeral range, the TraCI
client can be connected to ITSELF (TCP simultaneous open). getVersion then reads its own request back."""
import socket, struct, sys
import traci, traci.connection as tconn

port = int(sys.argv[1]) if len(sys.argv) > 1 else 61234
real_socket = socket.socket


class SelfConnected(real_socket):
    """The client socket of traci, bound to the port it will connect to: the kernel then connects it to itself."""
    def connect(self, address):
        self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.bind(address)
        return real_socket.connect(self, address)


tconn.socket.socket = SelfConnected
try:
    traci.init(port, numRetries=0, label="default")
    print("unexpected: handshake succeeded")
except Exception as error:                               # what b_runner logged: error('unpack requires ...')
    print("1st start :", repr(error), "| type", type(error).__module__ + "." + type(error).__name__)
finally:
    tconn.socket.socket = real_socket
print("label 'default' still registered:", tconn.has("default"))
try:
    traci.start(["sumo", "--version"])
except Exception as error:
    print("next start:", repr(error))
