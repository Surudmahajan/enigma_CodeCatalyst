import { Ionicons } from '@expo/vector-icons';
import type { DirectPathway, ProcessedPathway } from '@symbio/shared-types';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Bar, Body, Button, Card, Chip, EmptyState, KeyValue, Notice, QueryState, ScoreRing, Screen, SectionHeader,
  Title, type IconName } from '@/components/ui';
import { useMembership } from '@/lib/auth-store';
import { formatMoney, formatNumber, percent } from '@/lib/format';
import { usePathways } from '@/lib/queries';
import { fontSize, radius, spacing, useColors } from '@/theme';

const STATUS_TONE = { VIABLE: 'accent', WEAK: 'warning', INSUFFICIENT_DATA: 'warning', NOT_VIABLE: 'danger' } as const;
const STATUS_LABEL = { VIABLE: 'Viable pathway', WEAK: 'Weak pathway', INSUFFICIENT_DATA: 'Economics not assessed', NOT_VIABLE: 'Not viable' } as const;
const SCORE_LABELS: Record<string, string> = { technical: 'Technical', quantity: 'Quantity', capacity: 'Processor capacity',
  logistics: 'Logistics (both legs)', timing: 'Timing', economic: 'Economic', environmental: 'Environmental' };

/** Seller → (Processor →) Buyer comparison. All calculation happens on the backend. */
export default function Pathways() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const c = useColors();
  const report = usePathways(id);
  const data = report.data;
  const [showFailed, setShowFailed] = useState(true);
  const processed = (data?.processed ?? []).filter((p) => showFailed || p.status !== 'NOT_VIABLE');

  return (
    <Screen refreshing={report.isRefetching} onRefresh={() => report.refetch()}>
      <QueryState query={report}>
        {data ? (
          <>
            <Title sub={`${data.material ?? 'Unclassified'} · ${data.supply}`}>{data.resource_name}</Title>
            <Notice tone={data.pathways_active ? 'accent' : 'warning'} icon="bulb-outline">{data.recommendation}</Notice>

            {data.pathways_active ? (<>
            <SectionHeader title="Pathway A · Sell as-is" />
            {data.direct.length ? data.direct.map((d) => <DirectCard key={d.match_id} d={d} />) : (
              <Card>
                <FlowNode icon="cube-outline" title="Raw material" subtitle={data.supply} />
                <Arrow label="" />
                <FlowNode icon="close-circle-outline" title="No direct buyer" subtitle="No active requirement accepts this material as-is." muted />
              </Card>
            )}

            <SectionHeader title="Pathway B · Process first"
              action={<Chip label={showFailed ? 'Hide non-viable' : 'Show non-viable'} onPress={() => setShowFailed(!showFailed)} />} />
            {processed.length ? processed.map((p, i) => <ProcessedCard key={p.id} p={p} defaultOpen={i === 0 && p.status === 'VIABLE'} />) : (
              <EmptyState icon="git-network-outline" title="No processing pathway found"
                message={data.transformations.length ? 'Processing methods exist for this material, but no processor/buyer combination is available right now.'
                  : 'No processing method is known for this material yet.'} />
            )}
            </>) : null}

            {data.transformations.length ? (
              <>
                <SectionHeader title="What this material can become" />
                {data.transformations.map((t) => (
                  <Card key={t.method_key}>
                    <Text style={{ color: c.text, fontWeight: '700', fontSize: fontSize.md }}>{t.output_material}</Text>
                    <Body muted>{t.method_name} · yield {percent(t.expected_yield)} · ~{t.processing_time_days} days</Body>
                    <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm }}>
                      <Chip label={t.input_status === 'COMPATIBLE' ? 'Input compatible' : t.input_status === 'NEEDS_DATA' ? 'Input needs data' : 'Input incompatible'}
                        tone={t.input_status === 'COMPATIBLE' ? 'accent' : t.input_status === 'NEEDS_DATA' ? 'warning' : 'danger'} />
                      <Chip label={`${t.processors_found} processor(s)`} tone="info" />
                    </View>
                  </Card>
                ))}
              </>
            ) : null}
            <Body muted style={{ fontSize: fontSize.xs, marginTop: spacing.lg }}>{data.disclaimer} ({data.version})</Body>
          </>
        ) : null}
      </QueryState>
    </Screen>
  );
}

function DirectCard({ d }: { d: DirectPathway }) {
  const c = useColors();
  return (
    <Card onPress={() => router.push(`/match/${d.match_id}`)} accessibilityLabel={`Direct sale to ${d.buyer.organization.display_name}`}>
      <View style={{ flexDirection: 'row', gap: spacing.md, alignItems: 'center' }}>
        <ScoreRing score={d.route_score} size={52} />
        <View style={{ flex: 1 }}>
          <Text style={{ color: c.text, fontWeight: '700', fontSize: fontSize.md }} numberOfLines={1}>{d.buyer.organization.display_name}</Text>
          <Body muted>{d.buyer.listing_name}</Body>
          <Body muted>{d.distance_km !== null && d.distance_km !== undefined ? `${Math.round(d.distance_km)} km · ` : ''}{percent(d.demand_coverage)} of demand · route score (same basis as processing)</Body>
        </View>
        <Ionicons name="chevron-forward" size={18} color={c.textMuted} />
      </View>
    </Card>
  );
}

function ProcessedCard({ p, defaultOpen }: { p: ProcessedPathway; defaultOpen: boolean }) {
  const c = useColors();
  const seller = useMembership()?.organization_name ?? 'You';
  const [open, setOpen] = useState(defaultOpen);
  const economics = p.economics as { currency: string; basis: string; net_value: number | null; direction: string | null;
    line_items: { key: string; label: string; amount: number | null; provenance: string; formula: string | null; hidden?: boolean }[];
    missing_inputs: string[]; hidden_note?: string };
  const env = p.environment as { waste_diverted_t: number; virgin_material_avoided_t: number; net_benefit_kgco2e: number | null; uses_demo_factors: boolean };
  const method = p.method as { name: string; steps: string[]; output_material: string; expected_yield: number;
    processing_time_days: number; output_specification: Record<string, number>; output_specification_label: string };
  const cap = p.processor_capacity as { available_t_per_month: number; capacity_t_per_month: number; city: string };
  const direct = p.direct_to_same_buyer;

  return (
    <Card style={{ borderColor: p.status === 'VIABLE' ? c.accent : c.border, borderWidth: p.status === 'VIABLE' ? 2 : 1 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginBottom: spacing.md }}>
        <ScoreRing score={p.overall_score} size={56} />
        <View style={{ flex: 1, gap: 4 }}>
          <Chip label={STATUS_LABEL[p.status]} tone={STATUS_TONE[p.status]} />
          <Text style={{ fontWeight: '700', color: c.text }}>via {p.processor.organization.display_name}</Text>
        </View>
      </View>

      <FlowNode icon="business-outline" title={seller} subtitle={`${formatNumber(p.input_quantity_t)} t ${p.basis} raw material`} />
      <Arrow label={p.distance_to_processor_km !== null && p.distance_to_processor_km !== undefined ? `≈${Math.round(p.distance_to_processor_km)} km` : ''} />
      <FlowNode icon="construct-outline" title={p.processor.organization.display_name}
        subtitle={`${method.steps.join(' + ')} · ${cap.city} · ${formatNumber(cap.available_t_per_month)} t/month free`}
        chip={p.capacity_status === 'SUFFICIENT' ? undefined : { label: `Capacity ${p.capacity_status.toLowerCase()}`, tone: p.capacity_status === 'PARTIAL' ? 'warning' : 'danger' }} />
      <Arrow label={`~${method.processing_time_days} days · yield ${percent(method.expected_yield)}`} />
      <FlowNode icon="layers-outline" title={method.output_material} subtitle={`${formatNumber(p.output_quantity_t)} t ${p.basis}`} />
      <Arrow label={p.distance_to_buyer_km !== null && p.distance_to_buyer_km !== undefined ? `≈${Math.round(p.distance_to_buyer_km)} km` : ''} />
      <FlowNode icon="storefront-outline" title={p.buyer.organization.display_name} subtitle={p.buyer.listing_name ?? ''}
        chip={{ label: p.buyer_wants === 'PROCESSED' ? 'Wants processed material' : 'Wants raw material', tone: 'info' }} />

      <View style={{ flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md }}>
        <Compare title="Direct to this buyer" value={direct.eligible ? percent(direct.overall_score) : 'Not feasible'}
          detail={direct.eligible ? 'Raw material accepted as-is' : direct.reason ?? ''} tone={direct.eligible ? 'info' : 'danger'} />
        <Compare title="Via processor" value={percent(p.overall_score)} detail={STATUS_LABEL[p.status]} tone={STATUS_TONE[p.status]} />
      </View>

      <Pressable onPress={() => setOpen(!open)} accessibilityRole="button" style={{ marginTop: spacing.md, minHeight: 40, justifyContent: 'center' }}>
        <Text style={{ color: c.info, fontWeight: '600' }}>{open ? 'Hide details' : p.blockers.length ? 'Why this pathway fails' : 'Why this pathway works'}</Text>
      </Pressable>
      {open ? (
        <>
          {p.blockers.map((b) => <Line key={b} icon="close-circle" color={c.danger} text={b} />)}
          {p.strengths.map((s) => <Line key={s} icon="checkmark-circle" color={c.accent} text={s} />)}
          {p.considerations.map((s) => <Line key={s} icon="alert-circle" color={c.warning} text={s} />)}

          <SectionHeader title="Feasibility" />
          {Object.entries(p.scores).map(([key, score]) => (
            <View key={key} style={{ marginBottom: spacing.sm }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <Text style={{ color: c.text }}>{SCORE_LABELS[key] ?? key}</Text>
                <Text style={{ color: c.textMuted }}>{score === null || score === undefined ? 'Not assessed' : percent(score)}</Text>
              </View>
              <View style={{ flexDirection: 'row', marginTop: 4 }}><Bar value={score} /></View>
            </View>
          ))}

          <SectionHeader title={`Pathway economics (${economics.basis})`} />
          {economics.line_items.map((li) => (
            <View key={li.key} style={{ marginBottom: spacing.xs }}>
              <KeyValue label={li.label} value={li.hidden ? 'Visible after connecting' : formatMoney(li.amount, economics.currency)} />
              <Text style={{ color: c.textMuted, fontSize: fontSize.xs }}>{li.provenance}{li.formula ? ` · ${li.formula}` : ''}</Text>
            </View>
          ))}
          {economics.net_value !== null ? <KeyValue label="Estimated net value" value={formatMoney(economics.net_value, economics.currency)} /> : null}
          {economics.hidden_note ? <Body muted>{economics.hidden_note}</Body> : null}
          {economics.missing_inputs.length ? <Body muted>Missing: {economics.missing_inputs.join(', ')}</Body> : null}

          <SectionHeader title="Output specification" />
          {Object.entries(method.output_specification).map(([k, v]) => <KeyValue key={k} label={k.replace(/_/g, ' ')} value={String(v)} />)}
          <Body muted style={{ fontSize: fontSize.xs }}>{method.output_specification_label}</Body>

          <SectionHeader title="Environmental potential" />
          <KeyValue label="Waste diverted" value={`${formatNumber(env.waste_diverted_t)} t`} />
          <KeyValue label="Virgin material avoided" value={`${formatNumber(env.virgin_material_avoided_t)} t`} />
          <KeyValue label="Net CO₂e" value={env.net_benefit_kgco2e !== null ? `${formatNumber(env.net_benefit_kgco2e)} kg` : 'Not assessed'} />
          {env.uses_demo_factors ? <Body muted style={{ fontSize: fontSize.xs }}>Uses illustrative demo emission factors.</Body> : null}

          <View style={{ marginTop: spacing.md }}>
            {p.connection_target.available && p.connection_target.match_id ? (
              <>
                <Body muted>{p.connection_target.relationship}</Body>
                <Button title={`Open opportunity with ${p.connection_target.with_organization}`} icon="person-add-outline" variant="secondary"
                  onPress={() => router.push(`/match/${p.connection_target.match_id}`)} />
                <Body muted style={{ fontSize: fontSize.xs }}>{p.connection_target.reason}</Body>
              </>
            ) : (
              <Notice>{p.connection_target.reason}</Notice>
            )}
          </View>
        </>
      ) : null}
    </Card>
  );
}

function FlowNode({ icon, title, subtitle, muted, chip }: {
  icon: IconName; title: string; subtitle: string; muted?: boolean;
  chip?: { label: string; tone: 'accent' | 'warning' | 'danger' | 'info' };
}) {
  const c = useColors();
  return (
    <View style={{ flexDirection: 'row', gap: spacing.md, alignItems: 'center', backgroundColor: c.surfaceMuted,
      borderRadius: radius.md, padding: spacing.md, opacity: muted ? 0.7 : 1 }}>
      <Ionicons name={icon} size={22} color={c.accent} />
      <View style={{ flex: 1 }}>
        <Text style={{ color: c.text, fontWeight: '700' }}>{title}</Text>
        {subtitle ? <Text style={{ color: c.textMuted, fontSize: fontSize.sm }}>{subtitle}</Text> : null}
        {chip ? <View style={{ marginTop: 4 }}><Chip label={chip.label} tone={chip.tone} /></View> : null}
      </View>
    </View>
  );
}

function Arrow({ label }: { label: string }) {
  const c = useColors();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingLeft: spacing.lg, paddingVertical: 2 }}>
      <Ionicons name="arrow-down" size={16} color={c.textMuted} />
      {label ? <Text style={{ color: c.textMuted, fontSize: fontSize.xs }}>{label}</Text> : null}
    </View>
  );
}

function Compare({ title, value, detail, tone }: { title: string; value: string; detail: string; tone: 'accent' | 'warning' | 'danger' | 'info' }) {
  const c = useColors();
  const color = { accent: c.accent, warning: c.warning, danger: c.danger, info: c.info }[tone];
  return (
    <View style={{ flex: 1, borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm }}>
      <Text style={{ color: c.textMuted, fontSize: fontSize.xs }}>{title}</Text>
      <Text style={{ color, fontWeight: '800', fontSize: fontSize.md }}>{value}</Text>
      <Text style={{ color: c.textMuted, fontSize: fontSize.xs }} numberOfLines={3}>{detail}</Text>
    </View>
  );
}

function Line({ icon, color, text }: { icon: IconName; color: string; text: string }) {
  return (
    <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.xs }}>
      <Ionicons name={icon} size={18} color={color} />
      <Body style={{ flex: 1 }}>{text}</Body>
    </View>
  );
}
