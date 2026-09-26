import type { Message } from '@symbio/shared-types';
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from './api';
import { useAuth } from './auth-store';
import { WS_URL, API_PREFIX } from './config';
import { keys } from './queries';

type ServerFrame =
  | { type: 'message'; message: Omit<Message, 'is_mine' | 'read_by_counterpart'> }
  | { type: 'ack'; client_id: string; message_id: string }
  | { type: 'read' | 'typing' | 'pong' | 'conversation_closed' | 'error'; [key: string]: unknown };

/**
 * Realtime channel for one conversation. Messages are always persisted by the
 * server before broadcast, so on reconnect we simply refetch history; if the
 * socket is down, sends fall back to REST (same idempotent client_id).
 */
export function useConversationSocket(conversationId: string) {
  const queryClient = useQueryClient();
  const token = useAuth((s) => s.accessToken);
  const organizationId = useAuth((s) => s.organizationId);
  const socket = useRef<WebSocket | null>(null);
  const retry = useRef(0);
  const [connected, setConnected] = useState(false);
  const [typing, setTyping] = useState(false);
  const [closed, setClosed] = useState(false);

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: keys.messages(conversationId) }),
    [queryClient, conversationId],
  );

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const open = () => {
      const ws = new WebSocket(`${WS_URL}${API_PREFIX}/ws/conversations/${conversationId}?token=${encodeURIComponent(token)}`);
      socket.current = ws;
      ws.onopen = () => { retry.current = 0; setConnected(true); refresh(); };
      ws.onmessage = (event) => {
        const frame = JSON.parse(String(event.data)) as ServerFrame;
        if (frame.type === 'message' || frame.type === 'read') refresh();
        if (frame.type === 'typing') { setTyping(true); setTimeout(() => setTyping(false), 3000); }
        if (frame.type === 'conversation_closed') { setClosed(true); refresh(); }
      };
      ws.onclose = (event) => {
        setConnected(false);
        if (cancelled || event.code === 4403) return; // 4403 = not authorized for this channel
        const delay = Math.min(30_000, 1000 * 2 ** retry.current++); // exponential backoff
        timer = setTimeout(open, delay);
      };
    };
    open();
    return () => { cancelled = true; if (timer) clearTimeout(timer); socket.current?.close(); };
  }, [conversationId, token, refresh]);

  const send = useCallback(async (text: string, clientId: string) => {
    const ws = socket.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'message', text, client_id: clientId }));
      return;
    }
    await api.post(`/conversations/${conversationId}/messages`, { text, client_id: clientId });
    refresh();
  }, [conversationId, refresh]);

  const notifyTyping = useCallback(() => {
    const ws = socket.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'typing' }));
  }, []);

  return { connected, typing, closed, send, notifyTyping, organizationId };
}
