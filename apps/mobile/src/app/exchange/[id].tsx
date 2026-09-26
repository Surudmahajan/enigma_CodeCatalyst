import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, View } from 'react-native';

import { Body, Button, Card, KeyValue, Notice, QueryState, Screen, SectionHeader, StatusBadge, TextField, Title } from '@/components/ui';
import { errorMessage } from '@/lib/api';
import { useCan } from '@/lib/auth-store';
import { formatDate, formatMoney, formatNumber, formatQuantity } from '@/lib/format';
import { useExchange, useExchangeAction } from '@/lib/queries';
import { spacing } from '@/theme';

export default function ExchangeDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const exchange = useExchange(id);
  const action = useExchangeAction(id);
  const canManage = useCan('MANAGE_EXCHANGES');
  const [delivered, setDelivered] = useState('');
  const e = exchange.data;

  const run = (a: 'start' | 'pause' | 'complete' | 'cancel' | 'fail', body?: unknown) =>
    action.mutate({ action: a, body }, { onError: (err) => Alert.alert('Could not update the exchange', errorMessage(err)) });

  const confirm = (a: 'cancel' | 'fail', label: string) => Alert.alert(`${label} this exchange?`, 'Both organizations are notified.', [
    { text: 'Keep', style: 'cancel' }, { text: label, style: 'destructive', onPress: () => run(a, { reason: null }) }]);

  return (
    <Screen refreshing={exchange.isRefetching} onRefresh={() => exchange.refetch()}>
      <QueryState query={exchange}>
        {e ? (
          <>
            <Title sub={`${e.provider.display_name} → ${e.demander.display_name}`}>{e.resource_name}</Title>
            <View style={{ marginBottom: spacing.md }}><StatusBadge status={e.status} /></View>
            <Card>
              <KeyValue icon="cube-outline" label="Agreed" value={formatQuantity(e.agreed_quantity, e.unit, e.agreed_frequency)} />
              <KeyValue icon="pricetag-outline" label="Price" value={e.agreed_price_per_unit ? `${formatMoney(e.agreed_price_per_unit, e.currency)}/${e.unit}` : '—'} />
              <KeyValue icon="calendar-outline" label="Term" value={`${formatDate(e.start_date)} → ${formatDate(e.end_date)}`} />
              <KeyValue icon="play-outline" label="Started" value={e.started_at ? formatDate(e.started_at) : '—'} />
              <KeyValue icon="flag-outline" label="Completed" value={e.completed_at ? formatDate(e.completed_at) : '—'} />
              {e.delivered_quantity ? <KeyValue icon="checkmark-done-outline" label="Delivered" value={`${formatNumber(e.delivered_quantity)} ${e.unit}`} /> : null}
              {e.status_reason ? <Body muted>{e.status_reason}</Body> : null}
            </Card>
            {e.notes ? <Card><Body>{e.notes}</Body></Card> : null}

            {canManage && e.allowed_transitions.length ? (
              <>
                <SectionHeader title="Update status" />
                <View style={{ gap: spacing.sm }}>
                  {e.allowed_transitions.includes('IN_PROGRESS') ? <Button title={e.status === 'PAUSED' ? 'Resume' : 'Start deliveries'} icon="play" onPress={() => run('start')} loading={action.isPending} /> : null}
                  {e.allowed_transitions.includes('COMPLETED') ? (
                    <Card>
                      <TextField label="Total quantity delivered (optional)" value={delivered} onChangeText={setDelivered}
                        keyboardType="decimal-pad" hint="Recorded as a party-reported outcome for impact tracking." />
                      <Button title="Mark completed" icon="flag" onPress={() => run('complete', { delivered_quantity: delivered || null })} />
                    </Card>
                  ) : null}
                  {e.allowed_transitions.includes('PAUSED') ? <Button title="Pause" variant="secondary" onPress={() => run('pause', { reason: null })} /> : null}
                  {e.allowed_transitions.includes('FAILED') ? <Button title="Mark failed" variant="secondary" onPress={() => confirm('fail', 'Mark failed')} /> : null}
                  {e.allowed_transitions.includes('CANCELLED') ? <Button title="Cancel exchange" variant="danger" onPress={() => confirm('cancel', 'Cancel')} /> : null}
                </View>
              </>
            ) : null}
            {e.status === 'COMPLETED' ? (
              <Notice tone="accent">Impact has been recorded for this exchange. See the impact dashboard for figures and methodology.</Notice>
            ) : null}
            <Button title="Open opportunity" variant="ghost" onPress={() => router.push(`/match/${e.match_id}`)} />
          </>
        ) : null}
      </QueryState>
    </Screen>
  );
}
