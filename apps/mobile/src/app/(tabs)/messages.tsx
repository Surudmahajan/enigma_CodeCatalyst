import { router } from 'expo-router';
import { Alert, Text, View } from 'react-native';

import { Body, Button, Card, Chip, EmptyState, QueryState, Screen, SectionHeader, StatusBadge, Title } from '@/components/ui';
import { errorMessage } from '@/lib/api';
import { useCan } from '@/lib/auth-store';
import { timeAgo } from '@/lib/format';
import { useConnectionAction, useConnections, useConversations } from '@/lib/queries';
import { fontSize, spacing, useColors } from '@/theme';

/** Connection requests + private channels. Messaging exists only inside accepted connections. */
export default function Messages() {
  const c = useColors();
  const connections = useConnections();
  const conversations = useConversations();
  const act = useConnectionAction();
  const canRespond = useCan('MANAGE_CONNECTIONS');
  const pending = (connections.data ?? []).filter((x) => x.status === 'PENDING');

  const respond = (id: string, action: 'accept' | 'reject' | 'withdraw') =>
    act.mutate({ id, action }, {
      onSuccess: (connection) => {
        if (action === 'accept' && connection.conversation_id) router.push(`/conversation/${connection.conversation_id}`);
      },
      onError: (e) => Alert.alert('Could not update the request', errorMessage(e)),
    });

  return (
    <Screen refreshing={conversations.isRefetching} onRefresh={() => { connections.refetch(); conversations.refetch(); }}>
      <Title sub="Private, opportunity-specific channels">Messages</Title>
      {pending.length ? <SectionHeader title="Connection requests" /> : null}
      {pending.map((x) => (
        <Card key={x.id} onPress={() => router.push(`/match/${x.match_id}`)}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text style={{ color: c.text, fontSize: fontSize.lg, fontWeight: '700', flex: 1 }}>{x.counterpart.display_name}</Text>
            <Chip label={x.direction === 'incoming' ? 'Incoming' : 'Sent'} tone={x.direction === 'incoming' ? 'warning' : 'info'} />
          </View>
          <Body muted>{x.resource_name} → {x.requirement_name}</Body>
          {x.message ? <Body style={{ marginTop: spacing.sm, fontStyle: 'italic' }}>“{x.message}”</Body> : null}
          {x.can_respond && canRespond ? (
            <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md }}>
              <Button title="Accept" icon="checkmark" onPress={() => respond(x.id, 'accept')} style={{ flex: 1 }} loading={act.isPending} />
              <Button title="Decline" variant="secondary" onPress={() => respond(x.id, 'reject')} style={{ flex: 1 }} />
            </View>
          ) : x.direction === 'outgoing' && canRespond ? (
            <Button title="Withdraw request" variant="ghost" onPress={() => respond(x.id, 'withdraw')} />
          ) : null}
        </Card>
      ))}

      <SectionHeader title="Channels" />
      <QueryState query={conversations}>
        {conversations.data?.length ? conversations.data.map((cv) => (
          <Card key={cv.id} onPress={() => router.push(`/conversation/${cv.id}`)} accessibilityLabel={`Chat with ${cv.counterpart.display_name}`}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm }}>
              <Text style={{ color: c.text, fontSize: fontSize.lg, fontWeight: '700', flex: 1 }} numberOfLines={1}>
                {cv.counterpart.display_name}
              </Text>
              {cv.unread_count ? <Chip label={`${cv.unread_count} new`} tone="accent" /> : null}
            </View>
            <Body muted>{cv.resource_name} → {cv.requirement_name}</Body>
            <Text style={{ color: c.textMuted, marginTop: spacing.xs }} numberOfLines={1}>
              {cv.last_message ? `${cv.last_message.is_mine ? 'You: ' : ''}${cv.last_message.body ?? cv.last_message.document?.file_name ?? ''}` : ''}
            </Text>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: spacing.sm }}>
              <StatusBadge status={cv.status === 'CLOSED' ? 'REVOKED' : cv.match_status} />
              {cv.last_message_at ? <Text style={{ color: c.textMuted, fontSize: fontSize.xs }}>{timeAgo(cv.last_message_at)}</Text> : null}
            </View>
          </Card>
        )) : (
          <EmptyState icon="chatbubbles-outline" title="No private channels yet"
            message="A channel opens when both organizations accept a connection on a specific opportunity." />
        )}
      </QueryState>
    </Screen>
  );
}
