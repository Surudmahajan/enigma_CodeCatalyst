import { Ionicons } from '@expo/vector-icons';
import { Redirect } from 'expo-router';
import { Tabs } from 'expo-router/js-tabs';
import type { ColorValue } from 'react-native';

import { useAuth } from '@/lib/auth-store';
import { useConversations, useUnreadCount } from '@/lib/queries';
import { useColors } from '@/theme';

type IconName = React.ComponentProps<typeof Ionicons>['name'];
const icon = (name: IconName) => ({ color, size }: { color: ColorValue; size: number }) =>
  <Ionicons name={name} color={color as string} size={size} />;

export default function TabsLayout() {
  const c = useColors();
  const { status, me } = useAuth();
  const conversations = useConversations();
  const unread = useUnreadCount();
  if (status === 'signedOut') return <Redirect href="/login" />;
  if (status === 'signedIn' && !me?.memberships.length) return <Redirect href="/onboarding" />;
  const unreadMessages = (conversations.data ?? []).reduce((n, cv) => n + cv.unread_count, 0);

  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: c.accent, tabBarInactiveTintColor: c.textMuted,
      tabBarStyle: { backgroundColor: c.surface, borderTopColor: c.border, minHeight: 60 },
      headerStyle: { backgroundColor: c.surface }, headerTitleStyle: { color: c.text, fontWeight: '700' } }}>
      <Tabs.Screen name="index" options={{ title: 'Dashboard', tabBarIcon: icon('grid-outline') }} />
      <Tabs.Screen name="listings" options={{ title: 'Listings', tabBarIcon: icon('layers-outline') }} />
      <Tabs.Screen name="matches" options={{ title: 'Opportunities', tabBarIcon: icon('git-compare-outline') }} />
      <Tabs.Screen name="messages" options={{ title: 'Messages', tabBarIcon: icon('chatbubbles-outline'),
        tabBarBadge: unreadMessages > 0 ? unreadMessages : undefined }} />
      <Tabs.Screen name="more" options={{ title: 'More', tabBarIcon: icon('person-circle-outline'),
        tabBarBadge: (unread.data?.unread ?? 0) > 0 ? unread.data?.unread : undefined }} />
    </Tabs>
  );
}
