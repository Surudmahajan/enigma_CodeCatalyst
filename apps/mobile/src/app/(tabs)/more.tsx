import { router } from 'expo-router';
import { Text } from 'react-native';

import { Body, Button, Card, EmptyState, KeyValue, QueryState, Screen, SectionHeader, StatusBadge, Title } from '@/components/ui';
import { useAuth, useMembership } from '@/lib/auth-store';
import { formatQuantity } from '@/lib/format';
import { useExchanges, useOrganization, useUnreadCount } from '@/lib/queries';
import { fontSize, useColors } from '@/theme';

export default function More() {
  const c = useColors();
  const { me, signOut, setOrganization } = useAuth();
  const membership = useMembership();
  const org = useOrganization();
  const exchanges = useExchanges();
  const unread = useUnreadCount();

  return (
    <Screen>
      <Title sub={me?.email}>{me ? `${me.first_name} ${me.last_name}` : 'Account'}</Title>
      <Card>
        <KeyValue icon="business-outline" label="Organization" value={membership?.organization_name ?? '—'} />
        <KeyValue icon="shield-outline" label="Your role" value={membership?.role ?? '—'} />
        <KeyValue icon="checkmark-circle-outline" label="Verification" value={membership?.verification_status ?? '—'} />
        <KeyValue icon="swap-vertical-outline" label="Workspace" value={membership?.operating_mode ?? '—'} />
        <QueryState query={org}>
          {org.data ? <KeyValue icon="location-outline" label="Facilities" value={String(org.data.facilities.length)} /> : null}
        </QueryState>
      </Card>
      {(me?.memberships.length ?? 0) > 1 ? (
        <>
          <SectionHeader title="Switch organization" />
          {me?.memberships.map((m) => (
            <Button key={m.organization_id} title={m.organization_name} variant={m.organization_id === membership?.organization_id ? 'primary' : 'secondary'}
              onPress={() => setOrganization(m.organization_id)} style={{ marginBottom: 8 }} />
          ))}
        </>
      ) : null}

      <SectionHeader title="Activity" />
      <Button title={`Notifications${unread.data?.unread ? ` (${unread.data.unread})` : ''}`} icon="notifications-outline"
        variant="secondary" onPress={() => router.push('/notifications')} style={{ marginBottom: 8 }} />
      <Button title="Impact dashboard" icon="leaf-outline" variant="secondary" onPress={() => router.push('/impact')} />

      <SectionHeader title="Exchanges" />
      <QueryState query={exchanges}>
        {exchanges.data?.length ? exchanges.data.map((e) => (
          <Card key={e.id} onPress={() => router.push(`/exchange/${e.id}`)}>
            <Text style={{ color: c.text, fontSize: fontSize.lg, fontWeight: '700' }}>{e.resource_name}</Text>
            <Body muted>{e.my_side === 'PROVIDER' ? `To ${e.demander.display_name}` : `From ${e.provider.display_name}`}</Body>
            <Body>{formatQuantity(e.agreed_quantity, e.unit, e.agreed_frequency)}</Body>
            <StatusBadge status={e.status} />
          </Card>
        )) : <EmptyState icon="swap-horizontal-outline" title="No exchanges yet"
          message="Once connected parties agree terms, record the exchange from the opportunity or chat." />}
      </QueryState>

      <SectionHeader title="Session" />
      <Button title="Sign out" variant="danger" icon="log-out-outline" onPress={async () => { await signOut(); router.replace('/login'); }} />
    </Screen>
  );
}
