import { Ionicons } from '@expo/vector-icons';
import type { Message } from '@symbio/shared-types';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Alert, FlatList, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Chip, ErrorState, OfflineBanner, Skeleton } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { useCan } from '@/lib/auth-store';
import { clientId, timeAgo } from '@/lib/format';
import { useConversation, useMessages } from '@/lib/queries';
import { pickDocument, uploadDocument } from '@/lib/upload';
import { useConversationSocket } from '@/lib/ws';
import { fontSize, radius, spacing, touchTarget, useColors } from '@/theme';

export default function ConversationScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const c = useColors();
  const conversation = useConversation(id);
  const messages = useMessages(id);
  const socket = useConversationSocket(id);
  const canSend = useCan('SEND_MESSAGES');
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const list = useRef<FlatList<Message>>(null);
  const cv = conversation.data;
  const readOnly = cv?.status === 'CLOSED' || socket.closed;

  useEffect(() => {
    if (messages.data?.length) api.post(`/conversations/${id}/read`).catch(() => undefined);
  }, [id, messages.data?.length]);

  const send = async () => {
    const body = text.trim();
    if (!body) return;
    setSending(true);
    try {
      await socket.send(body, clientId());
      setText('');
    } catch (e) {
      Alert.alert('Message not sent', `${errorMessage(e)} Your text is kept — try again.`);
    } finally {
      setSending(false);
    }
  };

  const attach = async () => {
    const file = await pickDocument();
    if (!file) return;
    try {
      await uploadDocument(file, { conversation_id: id });
      messages.refetch();
    } catch (e) {
      Alert.alert('Upload failed', errorMessage(e));
    }
  };

  const renderItem = ({ item }: { item: Message }) => {
    if (item.message_type === 'SYSTEM' || item.message_type === 'STRUCTURED_UPDATE') {
      return (
        <View style={[styles.system, { backgroundColor: c.surfaceMuted }]}>
          <Text style={{ color: c.textMuted, fontSize: fontSize.sm, textAlign: 'center' }}>{item.body}</Text>
          {typeof item.extra?.exchange_id === 'string' ? (
            <Pressable onPress={() => router.push(`/exchange/${item.extra.exchange_id as string}`)}>
              <Text style={{ color: c.info, textAlign: 'center', marginTop: 4 }}>View exchange</Text>
            </Pressable>
          ) : null}
        </View>
      );
    }
    const mine = item.is_mine;
    return (
      <View style={[styles.bubbleRow, { justifyContent: mine ? 'flex-end' : 'flex-start' }]}>
        <View style={[styles.bubble, { backgroundColor: mine ? c.primary : c.surface, borderColor: c.border }]}>
          {!mine && item.sender_name ? <Text style={{ color: c.accent, fontSize: fontSize.xs, fontWeight: '700' }}>{item.sender_name}</Text> : null}
          {item.document ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Ionicons name="document-attach-outline" size={18} color={mine ? c.onPrimary : c.text} />
              <Text style={{ color: mine ? c.onPrimary : c.text, fontWeight: '600' }}>{String(item.document.file_name)}</Text>
            </View>
          ) : null}
          {item.body ? <Text style={{ color: mine ? c.onPrimary : c.text, fontSize: fontSize.md }}>{item.body}</Text> : null}
          <Text style={{ color: mine ? c.onPrimary : c.textMuted, fontSize: fontSize.xs, opacity: 0.8, marginTop: 2 }}>
            {timeAgo(item.created_at)}{mine ? (item.read_by_counterpart ? ' · Read' : ' · Sent') : ''}
          </Text>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: c.background }}>
      <Stack.Screen options={{ title: cv?.counterpart.display_name ?? 'Private channel' }} />
      <OfflineBanner />
      {cv ? (
        <Pressable onPress={() => router.push(`/match/${cv.match_id}`)}
          style={[styles.context, { backgroundColor: c.surface, borderColor: c.border }]}>
          <Text style={{ color: c.text, fontWeight: '600', flex: 1 }} numberOfLines={1}>{cv.resource_name} → {cv.requirement_name}</Text>
          <Chip label={socket.connected ? 'Live' : 'Syncing'} tone={socket.connected ? 'accent' : 'warning'} />
        </Pressable>
      ) : null}
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
        {messages.isLoading ? <View style={{ padding: spacing.lg }}><Skeleton height={48} count={5} /></View>
          : messages.isError ? <ErrorState message={errorMessage(messages.error)} onRetry={() => messages.refetch()} />
          : (
            <FlatList ref={list} data={messages.data ?? []} keyExtractor={(m) => m.id} renderItem={renderItem}
              contentContainerStyle={{ padding: spacing.md }} onContentSizeChange={() => list.current?.scrollToEnd({ animated: false })}
              ListEmptyComponent={<Text style={{ color: c.textMuted, textAlign: 'center' }}>No messages yet.</Text>} />
          )}
        {socket.typing ? <Text style={{ color: c.textMuted, paddingHorizontal: spacing.lg }}>typing…</Text> : null}
        {readOnly ? (
          <Text style={{ color: c.textMuted, padding: spacing.lg, textAlign: 'center' }}>This connection has ended. The conversation is read-only.</Text>
        ) : canSend ? (
          <View style={[styles.composer, { borderColor: c.border, backgroundColor: c.surface }]}>
            <Pressable onPress={attach} accessibilityLabel="Attach document" style={styles.iconButton}>
              <Ionicons name="attach" size={24} color={c.textMuted} />
            </Pressable>
            <TextInput value={text} onChangeText={(v) => { setText(v); socket.notifyTyping(); }} placeholder="Message"
              placeholderTextColor={c.textMuted} multiline maxLength={4000} accessibilityLabel="Message"
              style={{ flex: 1, color: c.text, fontSize: fontSize.md, maxHeight: 120, paddingVertical: spacing.sm }} />
            <Pressable onPress={send} disabled={sending || !text.trim()} accessibilityLabel="Send" style={styles.iconButton}>
              <Ionicons name="send" size={22} color={text.trim() ? c.accent : c.textMuted} />
            </Pressable>
          </View>
        ) : (
          <Text style={{ color: c.textMuted, padding: spacing.lg, textAlign: 'center' }}>Your role can read but not send messages.</Text>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  context: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.md, borderBottomWidth: 1 },
  system: { alignSelf: 'center', borderRadius: radius.md, padding: spacing.sm, marginVertical: spacing.sm, maxWidth: '90%' },
  bubbleRow: { flexDirection: 'row', marginVertical: 4 },
  bubble: { maxWidth: '80%', borderRadius: radius.lg, padding: spacing.md, borderWidth: StyleSheet.hairlineWidth },
  composer: { flexDirection: 'row', alignItems: 'flex-end', borderTopWidth: 1, paddingHorizontal: spacing.sm },
  iconButton: { width: touchTarget, height: touchTarget, alignItems: 'center', justifyContent: 'center' },
});
