// Socket.IO singleton — realtime engine stream over the JWT-authenticated proxy.
import { io, Socket } from 'socket.io-client';
import { tokenStore } from '../api/client';
import { API_BASE_URL } from '../config/env';

let socket: Socket | null = null;

export async function getSocket(): Promise<Socket> {
  if (socket && socket.connected) return socket;
  if (socket) return socket; // connecting — reuse
  const token = await tokenStore.access();
  socket = io(`${API_BASE_URL}/bot`, {
    path: '/bot/socket.io',
    transports: ['polling'], // RN-safe; upgrade handled by engine.io
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
  }
}
