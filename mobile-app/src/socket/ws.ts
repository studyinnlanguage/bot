// Socket.IO singleton — realtime engine stream over the JWT-authenticated proxy.
import { io, Socket } from 'socket.io-client';
import { tokenStore } from '../api/client';
import { API_BASE_URL } from '../config/env';

let socket: Socket | null = null;
// Access token the current socket was opened with. The SaaS proxy re-validates
// the bearer token on every polling request, so a stale token silently kills
// the stream — recreate the socket whenever the access token rotates.
let socketToken = '';

export async function getSocket(): Promise<Socket> {
  const token = await tokenStore.access();
  if (socket && socketToken === token) return socket; // healthy or reconnecting
  if (socket) {
    socket.removeAllListeners();
    socket.disconnect();
    socket = null;
  }
  socketToken = token;
  socket = io(API_BASE_URL, {
    // Namespace MUST stay the default "/": the engine's SocketIO server only
    // emits on the root namespace. Passing `${API_BASE_URL}/bot` as the URI
    // makes the client join a "/bot" namespace that receives NO events
    // (handshake completes, stream stays empty). The engine.io path stays
    // "/bot/socket.io" — the SaaS proxy forwards it to the engine.
    path: '/bot/socket.io',
    transports: ['polling'], // RN-safe; websocket upgrade is not proxied
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 15000,
    timeout: 20000,
    extraHeaders: { Authorization: `Bearer ${token}` },
  });
  return socket;
}

export function closeSocket() {
  if (socket) {
    socket.removeAllListeners();
    socket.disconnect();
    socket = null;
    socketToken = '';
  }
}
