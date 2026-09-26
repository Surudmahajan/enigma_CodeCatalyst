import type { Notification } from '@symbio/shared-types';
import { useQueryClient } from '@tanstack/react-query';
import { type Href, router } from 'expo-router';
import { Text, View } from 'react-native';

import { Body, Button, Card, EmptyState, QueryState, Screen, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { timeAgo } from '@/lib/format';
import { keys, useNotifications } from '@/lib/queries';
import { fontSize, spacing, useColors } from '@/theme';

function target(n: Notification): Href | null {
  const d = n.data as Record<string, string | undefined>;
  if (d.conversation_id) return `/conversation/${d.conversation_id}` as Href;
  if (d.exchange_id) return `/exchange/${d.exchange_id}` as Href;
  if (d.match_id) return `/match/${d.match_id}` as Href;
  if (d.resource_id) return `/resource/${d.resource_id}` as Href;
  if (d.requirement_id) return `/requirement/${d.requirement_id}` as Href;
  return null;
}

export default function Notifications() {
  const c = useColors();
  const client = useQueryClient();
  const notifications = useNotifications();

  const open = async (n: Notification) => {
    if (!n.read_at) await api.post(`/notifications/${n.id}/read`).catch(() => undefined);
    client.invalidateQueries({ queryKey: keys.notifications });
    client.invalidateQueries({ queryKey: keys.unread });
    const href = target(n);
    if (href) router.push(href);
  };

  const readAll = async () => {
    await api.post('/notifications/read-all');
    client.invalidateQueries({ queryKey: keys.notifications });
    client.invalidateQueries({ queryKey: keys.unread });
  };

  return (
    <Screen refreshing={notifications.isRefetching} onRefresh={() => notifications.refetch()}>
      <Title>Notifications</Title>
      <Button title="Mark all as read" variant="ghost" onPress={readAll} />
      <QueryState query={notifications}>
        {notifications.data?.length ? notifications.data.map((n) => (
          <Card key={n.id} onPress={() => open(n)} style={n.read_at ? { opacity: 0.7 } : undefined}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm }}>
              <Text style={{ color: c.text, fontWeight: n.read_at ? '500' : '800', fontSize: fontSize.md, flex: 1 }}>{n.title}</Text>
              <Text style={{ color: c.textMuted, fontSize: fontSize.xs }}>{timeAgo(n.created_at)}</Text>
            </View>
            <Body muted>{n.body}</Body>
          </Card>
        )) : <EmptyState icon="notifications-outline" title="You're all caught up"
          message="New matches, connection requests, messages and exchange updates appear here." />}
      </QueryState>
    </Screen>
  );
}
