import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, Text, View } from 'react-native';

import { Bar, Body, Button, Card, Chip, KeyValue, Notice, QueryState, ScoreRing, Screen, SectionHeader, StatusBadge,
  TextField } from '@/components/ui';
import { errorMessage } from '@/lib/api';
import { formatDate, formatMoney, formatNumber, formatQuantity, percent } from '@/lib/format';
import { useConnectionAction, useMatch, useMatchAction } from '@/lib/queries';
import { fontSize, spacing, useColors } from '@/theme';

type Component = { label: string; score: number | null; level: string; headline: string; evidence: string[] };
type LineItem = { key: string; label: string; amount: number | null; basis: string; provided_by: string; formula: string | null; hidden?: boolean };
type PropertyCheck = { property_key: string; name: string; importance: string; outcome: string; constraint: string; observed: string; measured: boolean };

const BASIS_LABEL: Record<string, string> = {
  USER_PROVIDED: 'User-provided', PLATFORM_ASSUMPTION: 'Platform assumption', SYSTEM_CALCULATED: 'System-calculated',
};
const OUTCOME_TONE: Record<string, 'accent' | 'warning' | 'danger' | 'info'> = {
  PASS: 'accent', LIKELY: 'info', UNCERTAIN: 'warning', UNKNOWN: 'warning', LIKELY_FAIL: 'danger', FAIL: 'danger',
};

/** Opportunity report: explainable assessment + the next step in the match lifecycle. */
export default function MatchReport() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const c = useColors();
  const match = useMatch(id);
  const action = useMatchAction(id);
  const connectionAction = useConnectionAction();
  const [note, setNote] = useState('');
  const [composing, setComposing] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const m = match.data;

  const run = (a: 'interest' | 'reject' | 'refresh' | 'connection-request', body?: unknown, done?: string) =>
    action.mutate({ action: a, body }, {
      onSuccess: () => { if (done) Alert.alert(done); setComposing(false); },
      onError: (e) => Alert.alert('Action failed', errorMessage(e)),
    });

  const explanation = (m?.explanation ?? {}) as {
    headline?: string; summary?: string; strengths?: string[]; considerations?: string[]; disclaimer?: string;
    components?: Record<string, Component>; property_checks?: PropertyCheck[]; caps_applied?: string[];
    confidence?: { score: number; level: string; gaps: string[] }; ai_summary?: { text: string; model: string };
  };
  const economic = m?.economic as undefined | { status: string; direction: string | null; currency: string; period: string;
    line_items: LineItem[]; net_value: number | null; assumptions: string[]; missing_inputs: string[]; notes: string[] };
  const environmental = m?.environmental as undefined | { waste_diverted: number | null; virgin_material_avoided: number | null;
    transport_kgco2e: number | null; net_benefit_kgco2e: number | null; quantity_unit: string; period: string;
    uses_demo_factors: boolean; assumptions: string[]; missing_inputs: string[]; factors_used: { key: string; source: string; version: string }[] };
  const closed = m && ['EXPIRED', 'REJECTED', 'CANCELLED'].includes(m.status);
  const has = (a: string) => m?.allowed_actions.includes(a);

  return (
    <Screen refreshing={match.isRefetching} onRefresh={() => match.refetch()}>
      <QueryState query={match}>
        {m ? (
          <>
            <View style={{ flexDirection: 'row', gap: spacing.lg, alignItems: 'center', marginBottom: spacing.lg }}>
              <ScoreRing score={m.overall_score} size={84} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: c.textMuted, fontSize: fontSize.sm }}>{explanation.headline ?? 'Potential opportunity'}</Text>
                <Text style={{ color: c.text, fontSize: fontSize.xl, fontWeight: '800' }}>{m.counterpart.display_name}</Text>
                <Text style={{ color: c.textMuted }}>{m.counterpart.industry_sector} · {m.counterpart.location?.city}</Text>
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.sm }}>
                  <StatusBadge status={m.status} />
                  {m.is_hidden_match ? <Chip label="Hidden match" tone="hidden" /> : null}
                  {m.requires_manual_review ? <Chip label="Manual review" tone="warning" /> : null}
                  {m.counterpart.verification_status === 'VERIFIED' ? <Chip label="Verified" tone="accent" /> : null}
                </View>
              </View>
            </View>

            {closed ? <Notice tone="danger">This opportunity is no longer active.{m.stale_reason ? ` ${m.stale_reason}` : ''}</Notice> : null}
            {!closed && m.stale_reason ? <Notice tone="warning">{m.stale_reason}</Notice> : null}

            <Card><Body>{explanation.summary}</Body></Card>
            {explanation.ai_summary ? (
              <Card><Chip label="AI wording" tone="hidden" /><Body style={{ marginTop: spacing.sm }}>{explanation.ai_summary.text}</Body></Card>
            ) : null}

            <SectionHeader title="Strengths" />
            {(explanation.strengths ?? []).map((s) => (
              <View key={s} style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.xs }}>
                <Ionicons name="checkmark-circle" size={18} color={c.accent} /><Body style={{ flex: 1 }}>{s}</Body>
              </View>
            ))}
            <SectionHeader title="Considerations" />
            {(explanation.considerations ?? []).map((s) => (
              <View key={s} style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.xs }}>
                <Ionicons name="alert-circle" size={18} color={c.warning} /><Body style={{ flex: 1 }}>{s}</Body>
              </View>
            ))}

            <SectionHeader title="Assessment" />
            <Card>
              {Object.entries(explanation.components ?? {}).map(([key, comp]) => (
                <Pressable key={key} onPress={() => setExpanded(expanded === key ? null : key)} accessibilityRole="button"
                  style={{ paddingVertical: spacing.sm }}>
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                    <Text style={{ color: c.text, fontWeight: '700' }}>{comp.label}</Text>
                    <Text style={{ color: c.textMuted }}>{comp.headline}</Text>
                  </View>
                  <View style={{ flexDirection: 'row', marginTop: 6 }}><Bar value={comp.score} /></View>
                  {expanded === key ? comp.evidence.map((e) => <Body key={e} muted style={{ marginTop: 4 }}>• {e}</Body>) : null}
                </Pressable>
              ))}
              {(explanation.caps_applied ?? []).map((cap) => <Body key={cap} muted>{cap}</Body>)}
            </Card>

            <Card>
              <KeyValue icon="shield-checkmark-outline" label="Data confidence"
                value={`${explanation.confidence?.level ?? m.confidence_level} (${percent(m.confidence)})`} />
              {(explanation.confidence?.gaps ?? []).map((g) => <Body key={g} muted>• {g}</Body>)}
            </Card>

            {explanation.property_checks?.length ? (
              <>
                <SectionHeader title="Technical checks" />
                {explanation.property_checks.map((p) => (
                  <Card key={p.property_key}>
                    <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text style={{ color: c.text, fontWeight: '700' }}>{p.name}</Text>
                      <Chip label={p.outcome.replace('_', ' ').toLowerCase()} tone={OUTCOME_TONE[p.outcome]} />
                    </View>
                    <Body muted>Needs {p.constraint} ({p.importance.toLowerCase()}) · observed {p.observed}</Body>
                  </Card>
                ))}
              </>
            ) : null}

            {economic ? (
              <>
                <SectionHeader title={`Economic estimate (${economic.period})`} />
                <Card>
                  {economic.line_items.map((li) => (
                    <View key={li.key} style={{ paddingVertical: spacing.xs }}>
                      <KeyValue label={li.label} value={li.hidden ? 'Visible after connecting' : formatMoney(li.amount, economic.currency)} />
                      <Text style={{ color: c.textMuted, fontSize: fontSize.xs }}>
                        {BASIS_LABEL[li.basis] ?? li.basis} · {li.provided_by}{li.formula ? ` · ${li.formula}` : ''}
                      </Text>
                    </View>
                  ))}
                  {economic.net_value !== null ? <KeyValue label="Potential net value" value={formatMoney(economic.net_value, economic.currency)} /> : null}
                  {economic.status === 'INSUFFICIENT_DATA' ? <Notice>Not enough price data to estimate value — no figure is invented.</Notice> : null}
                  {[...economic.assumptions, ...economic.notes].map((a) => <Body key={a} muted>• {a}</Body>)}
                  {economic.missing_inputs.length ? <Body muted>Missing: {economic.missing_inputs.join(', ')}</Body> : null}
                </Card>
              </>
            ) : null}

            {environmental ? (
              <>
                <SectionHeader title={`Environmental potential (${environmental.period})`} />
                <Card>
                  <KeyValue label="Waste diverted" value={environmental.waste_diverted !== null ? `${formatNumber(environmental.waste_diverted)} ${environmental.quantity_unit}` : '—'} />
                  <KeyValue label="Virgin material avoided" value={environmental.virgin_material_avoided !== null ? `${formatNumber(environmental.virgin_material_avoided)} ${environmental.quantity_unit}` : '—'} />
                  <KeyValue label="Transport emissions" value={environmental.transport_kgco2e !== null ? `${formatNumber(environmental.transport_kgco2e)} kgCO₂e` : 'Not assessed'} />
                  <KeyValue label="Net CO₂e benefit" value={environmental.net_benefit_kgco2e !== null ? `${formatNumber(environmental.net_benefit_kgco2e)} kgCO₂e` : 'Not assessed'} />
                  {environmental.uses_demo_factors ? <Notice tone="warning">Uses illustrative demo emission factors — not suitable for reporting.</Notice> : null}
                  {environmental.assumptions.map((a) => <Body key={a} muted>• {a}</Body>)}
                  {environmental.factors_used.map((f) => <Body key={f.key} muted>Factor {f.key} v{f.version}: {f.source}</Body>)}
                </Card>
              </>
            ) : null}

            <SectionHeader title="The listings" />
            {[m.resource, m.requirement].map((l) => (
              <Card key={l.id}>
                <Chip label={l.kind === 'RESOURCE' ? 'Provided' : 'Required'} tone={l.kind === 'RESOURCE' ? 'accent' : 'info'} />
                <Text style={{ color: c.text, fontWeight: '700', fontSize: fontSize.md, marginTop: spacing.sm }}>{l.name}</Text>
                <Body muted>{l.material?.canonical_name ?? l.intended_application?.name ?? ''}</Body>
                <KeyValue label="Quantity" value={formatQuantity(l.quantity, l.unit, l.frequency)} />
                <KeyValue label="Window" value={`${formatDate(l.window_start)} → ${formatDate(l.window_end)}`} />
                <KeyValue label="Location" value={`${l.location.city}${l.location.state ? `, ${l.location.state}` : ''}`} />
                {l.description ? <Body>{l.description}</Body> : null}
              </Card>
            ))}
            {m.counterpart_contact ? (
              <Card>
                <Text style={{ color: c.text, fontWeight: '700' }}>Contact (shared after connection)</Text>
                <KeyValue label="Legal name" value={m.counterpart_contact.legal_name} />
                <KeyValue label="Email" value={m.counterpart_contact.business_email ?? '—'} />
                <KeyValue label="Phone" value={m.counterpart_contact.business_phone ?? '—'} />
                <KeyValue label="Facility" value={`${m.counterpart_contact.facility_name}, ${m.counterpart_contact.facility_location.address ?? m.counterpart_contact.facility_location.city}`} />
              </Card>
            ) : <Notice>Contacts, prices, exact addresses and documents are shared only after both organizations accept a connection.</Notice>}

            <SectionHeader title="Next step" />
            {composing ? (
              <Card>
                <TextField label="Introduce your organization (optional)" value={note} onChangeText={setNote} multiline maxLength={500} />
                <Button title="Send connection request" icon="send" loading={action.isPending}
                  onPress={() => run('connection-request', { message: note || null }, 'Connection request sent')} />
                <Button title="Cancel" variant="ghost" onPress={() => setComposing(false)} />
              </Card>
            ) : (
              <View style={{ gap: spacing.sm }}>
                {has('REQUEST_CONNECTION') ? <Button title="Request connection" icon="person-add-outline" onPress={() => setComposing(true)} /> : null}
                {has('ACCEPT_CONNECTION') && m.connection ? (
                  <Button title="Accept connection" icon="checkmark" loading={connectionAction.isPending}
                    onPress={() => connectionAction.mutate({ id: String(m.connection!.id), action: 'accept' }, {
                      onSuccess: (x) => x.conversation_id && router.push(`/conversation/${x.conversation_id}`),
                      onError: (e) => Alert.alert('Could not accept', errorMessage(e)) })} />
                ) : null}
                {has('REJECT_CONNECTION') && m.connection ? (
                  <Button title="Decline connection" variant="secondary"
                    onPress={() => connectionAction.mutate({ id: String(m.connection!.id), action: 'reject' })} />
                ) : null}
                {has('OPEN_CHAT') && m.connection?.conversation_id ? (
                  <Button title="Open private channel" icon="chatbubbles-outline" onPress={() => router.push(`/conversation/${m.connection!.conversation_id}`)} />
                ) : null}
                {has('CREATE_EXCHANGE') ? (
                  <Button title="Record agreed exchange" icon="swap-horizontal-outline" variant="secondary"
                    onPress={() => router.push({ pathname: '/exchange/new', params: { matchId: m.id } })} />
                ) : null}
                {m.exchange_id ? <Button title="View exchange" variant="secondary" onPress={() => router.push(`/exchange/${m.exchange_id}`)} /> : null}
                {has('MARK_INTERESTED') ? <Button title="Mark as interested" variant="secondary" icon="star-outline" onPress={() => run('interest')} /> : null}
                {has('REFRESH') ? <Button title="Re-assess with latest data" variant="ghost" icon="refresh" onPress={() => run('refresh', undefined, 'Re-assessed')} /> : null}
                {has('REJECT') ? (
                  <Button title="Not relevant" variant="danger"
                    onPress={() => Alert.alert('Dismiss this opportunity?', 'Both organizations will see it as declined.', [
                      { text: 'Cancel', style: 'cancel' }, { text: 'Dismiss', style: 'destructive', onPress: () => run('reject', { reason: null }) }])} />
                ) : null}
              </View>
            )}
            <Body muted style={{ marginTop: spacing.lg, fontSize: fontSize.xs }}>
              {explanation.disclaimer} Assessment v{m.matching_version} · {m.methodology_version}
            </Body>
          </>
        ) : null}
      </QueryState>
    </Screen>
  );
}
