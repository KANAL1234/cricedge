import { io, Socket } from "socket.io-client";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

let socket: Socket | null = null;

function getSocket(): Socket {
  if (!socket) {
    socket = io(API_URL, {
      autoConnect: false,
      transports: ["websocket"],
      reconnectionAttempts: 5,
      reconnectionDelay: 2000,
    });

    socket.on("connect", () => {
      console.log("[Socket] Connected:", socket?.id);
    });

    socket.on("disconnect", (reason) => {
      console.log("[Socket] Disconnected:", reason);
    });

    socket.on("connect_error", (err) => {
      console.error("[Socket] Connection error:", err.message);
    });
  }
  return socket;
}

export function subscribeToMatch(matchId: string): void {
  const s = getSocket();
  if (!s.connected) {
    s.connect();
  }
  s.emit("subscribe", { match_id: matchId });
}

export function unsubscribeFromMatch(matchId: string): void {
  const s = getSocket();
  s.emit("unsubscribe", { match_id: matchId });
}

export { getSocket as socket };
export default getSocket;
