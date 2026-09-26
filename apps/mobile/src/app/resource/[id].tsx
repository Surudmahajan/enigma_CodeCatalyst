import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, Text, View } from 'react-native';

import { MatchCard } from '@/components/domain';
import { ListingActions } from '@/components/listing-actions';
import { Body, Button, Card, Chip, EmptyState, KeyValue, Notice, QueryState, Screen, SectionHeader, StatusBadge, Title } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { useCan } from '@/lib/auth-store';
import { formatDate, formatMoney, formatNumber, formatQuantity, statusLabel } from '@/lib/format';
import { useApplicationSuggestions, useConfirmProperty, useDocuments, useMatches, useResource } from '@/lib/queries';
import { pickDocument, uploadDocument } from '@/lib/upload';
import { fontSize, spacing, useColors } from '@/theme';

export default function ResourceDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const c = useColors();
  const resource = useResource(id);
  const matches = useMatches({ resource_id: id });
  const documents = useDocuments({ resource_id: id });
  const applications = useApplicationSuggestions(id);
  const confirm = useConfirmProperty(id);
  const canEdit = useCan('MANAGE_LISTINGS');
  const [busy, setBusy] = useState(false);
  const r = resource.data;

  const upload = async () => {
    const file = await pickDocument();
    if (!file) return;
    setBusy(true);
    try {
      await uploadDocument(file, { resource_id: id });
      await documents.refetch();
    } catch (e) {
      Alert.alert('Upload failed', errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const extract = async (documentId: string) => {
    setBusy(true);
    try {
      const result = await api.post<{ suggestions: unknown[]; skipped: unknown[]; notes: string[] }>(
        `/documents/${documentId}/extract`, { resource_id: id });
      await resource.refetch();
      Alert.alert('Extraction finished', `${result.suggestions.length} value(s) suggested for your review. ${result.notes.join(' ')}`);
    } catch (e) {
      Alert.alert('Extraction failed', errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen refreshing={resource.isRefetching} onRefresh={() => { resource.refetch(); matches.refetch(); }}>
      <QueryState query={resource}>
        {r ? (
          <>
            <Title sub={r.material ? `${r.material.canonical_name} · ${r.material.category}` : 'Not normalized'}>{r.name}</Title>
            <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md }}><StatusBadge status={r.status} /></View>
            {r.description ? <Body style={{ marginBottom: spacing.md }}>{r.description}</Body> : null}
            <Card>
              <KeyValue icon="cube-outline" label="Supply" value={formatQuantity(r.quantity_available, r.unit, r.frequency)} />
              <KeyValue icon="calendar-outline" label="Available" value={`${formatDate(r.availability_start)} → ${formatDate(r.availability_end)}`} />
              <KeyValue icon="location-outline" label="Facility" value={`${r.facility.name}, ${r.facility.location.city}`} />
              <KeyValue icon="construct-outline" label="Processing" value={r.processing_required ? r.processing_types.join(', ') || 'Required' : 'Direct use'} />
              <KeyValue icon="trash-outline" label="Today" value={statusLabel(r.current_disposition)} />
              <KeyValue icon="cash-outline" label="Disposal cost" value={r.disposal_cost_per_unit ? `${formatMoney(r.disposal_cost_per_unit, r.currency)}/${r.unit}` : '—'} />
              <KeyValue icon="pricetag-outline" label="Asking price" value={r.asking_price_per_unit ? `${formatMoney(r.asking_price_per_unit, r.currency)}/${r.unit}` : '—'} />
            </Card>

            <Card>
              <Text style={{ color: c.text, fontSize: fontSize.lg, fontWeight: '700' }}>Sell as-is, or process first?</Text>
              <Body muted>Compare direct buyers with Seller → Processor → Buyer pathways, including capacity, route and economics.</Body>
              <Button title="Discover processing pathways" icon="git-network-outline" style={{ marginTop: spacing.md }}
                onPress={() => router.push(`/pathways/${r.id}`)} />
            </Card>

            <SectionHeader title="Technical properties" />
            {r.properties.length ? r.properties.map((p) => (
              <Card key={p.id}>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text style={{ color: c.text, fontWeight: '700', fontSize: fontSize.md }}>{p.property_name}</Text>
                  <Text style={{ color: c.text, fontSize: fontSize.lg, fontWeight: '800' }}>
                    {p.value_numeric !== null && p.value_numeric !== undefined ? formatNumber(p.value_numeric, 3) : p.value_text} {p.unit ?? ''}
                  </Text>
                </View>
                <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm }}>
                  <Chip label={p.source === 'USER_INPUT' ? 'Entered by you' : p.source === 'AI_EXTRACTED' ? 'Extracted from document' : 'Verified'}
                    tone={p.source === 'AI_EXTRACTED' ? 'hidden' : 'info'} />
                  {!p.confirmed ? <Chip label="Needs confirmation" tone="warning" /> : null}
                </View>
                {!p.confirmed && canEdit ? (
                  <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md }}>
                    <Button title="Confirm" icon="checkmark" style={{ flex: 1 }} loading={confirm.isPending}
                      onPress={() => confirm.mutate({ valueId: p.id, accept: true }, { onError: (e) => Alert.alert('Could not confirm', errorMessage(e)) })} />
                    <Button title="Reject" variant="secondary" style={{ flex: 1 }}
                      onPress={() => confirm.mutate({ valueId: p.id, accept: false })} />
                  </View>
                ) : null}
              </Card>
            )) : <Notice>No measured properties yet. Values let demanders' technical constraints be verified.</Notice>}
            {r.properties.some((p) => !p.confirmed) ? (
              <Notice tone="warning">Unconfirmed values are ignored by matching until you confirm them.</Notice>
            ) : null}

            <SectionHeader title="Documents" />
            {(documents.data ?? []).map((d) => (
              <Card key={d.id}>
                <KeyValue icon="document-text-outline" label={d.file_name} value={`${Math.round(d.file_size / 1024)} KB`} />
                {canEdit ? <Button title="Extract properties" variant="ghost" icon="scan-outline" onPress={() => extract(d.id)} disabled={busy} /> : null}
              </Card>
            ))}
            {canEdit ? <Button title="Upload document" icon="cloud-upload-outline" variant="secondary" onPress={upload} loading={busy} /> : null}

            <SectionHeader title="Potential applications" />
            <QueryState query={applications}>
              {[...(applications.data?.curated ?? []), ...(applications.data?.related ?? []), ...(applications.data?.ai_ideas ?? [])].map((a) => (
                <Card key={`${a.source}-${a.application_key}`}>
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm }}>
                    <Text style={{ color: c.text, fontWeight: '700', flex: 1 }}>{a.application}</Text>
                    <Chip label={a.status.replace('_', ' ').toLowerCase()}
                      tone={a.status === 'ELIGIBLE' ? 'accent' : a.status === 'BLOCKED' ? 'danger' : a.status === 'UNVERIFIED' ? 'hidden' : 'warning'} />
                  </View>
                  {a.evidence.map((e) => <Body key={e} muted>• {e}</Body>)}
                </Card>
              ))}
            </QueryState>

            <SectionHeader title="Opportunities for this resource" />
            <QueryState query={matches}>
              {matches.data?.length ? matches.data.map((m) => <MatchCard key={m.id} match={m} />)
                : <EmptyState icon="search-outline" title="No matches yet"
                    message={r.status === 'ACTIVE' ? 'SYMBIO re-checks automatically when new requirements are published.' : 'Publish this resource to start matching.'} />}
            </QueryState>

            <SectionHeader title="Lifecycle" />
            <ListingActions kind="resources" id={r.id} status={r.status} allowed={r.allowed_transitions} />
          </>
        ) : null}
      </QueryState>
    </Screen>
  );
}
