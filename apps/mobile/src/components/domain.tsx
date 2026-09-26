import { Ionicons } from '@expo/vector-icons';
import type { MatchSummary, Requirement, Resource } from '@symbio/shared-types';
import { router } from 'expo-router';
import { useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { formatDate, formatQuantity, percent } from '@/lib/format';
import { fontSize, radius, spacing, touchTarget, useColors } from '@/theme';

import { Button, Card, Chip, ScoreRing, StatusBadge } from './ui';

export function MatchCard({ match }: { match: MatchSummary }) {
  const c = useColors();
  const closed = ['EXPIRED', 'REJECTED', 'CANCELLED'].includes(match.status);
  return (
    <Card onPress={() => router.push(`/match/${match.id}`)} accessibilityLabel={`Opportunity with ${match.counterpart.display_name}`}
      style={closed ? { opacity: 0.6 } : undefined}>
      <View style={styles.row}>
        <ScoreRing score={match.overall_score} size={56} />
        <View style={{ flex: 1 }}>
          <View style={[styles.row, { gap: spacing.xs, flexWrap: 'wrap' }]}>
            {match.is_new ? <Chip label="New" tone="info" /> : null}
            {match.is_hidden_match ? <Chip label="Hidden match" tone="hidden" /> : null}
            {match.requires_manual_review ? <Chip label="Review" tone="warning" /> : null}
          </View>
          <Text style={[styles.title, { color: c.text }]} numberOfLines={1}>{match.counterpart.display_name}</Text>
          <Text style={{ color: c.textMuted, fontSize: fontSize.sm }} numberOfLines={1}>
            {match.my_side === 'PROVIDER' ? `Needs: ${match.counterpart_listing_name}` : `Offers: ${match.counterpart_listing_name}`}
          </Text>
        </View>
        <Ionicons name="chevron-forward" size={20} color={c.textMuted} />
      </View>
      <View style={[styles.row, { marginTop: spacing.md, gap: spacing.lg }]}>
        <Meta icon="swap-horizontal" text={`${percent(match.demand_coverage)} of demand`} />
        <Meta icon="navigate-outline" text={match.distance_km !== null && match.distance_km !== undefined ? `${Math.round(match.distance_km)} km` : '—'} />
        <Meta icon="shield-checkmark-outline" text={`${match.confidence_level.toLowerCase()} confidence`} />
      </View>
      {match.stale_reason ? <Text style={{ color: c.danger, fontSize: fontSize.sm, marginTop: spacing.sm }}>{match.stale_reason}</Text> : null}
      <View style={{ marginTop: spacing.sm }}><StatusBadge status={match.status} /></View>
    </Card>
  );
}

function Meta({ icon, text }: { icon: React.ComponentProps<typeof Ionicons>['name']; text: string }) {
  const c = useColors();
  return (
    <View style={[styles.row, { gap: 4 }]}>
      <Ionicons name={icon} size={14} color={c.textMuted} />
      <Text style={{ color: c.textMuted, fontSize: fontSize.xs }}>{text}</Text>
    </View>
  );
}

export function ResourceCard({ resource }: { resource: Resource }) {
  const c = useColors();
  return (
    <Card onPress={() => router.push(`/resource/${resource.id}`)} accessibilityLabel={resource.name}>
      <View style={[styles.row, { justifyContent: 'space-between' }]}>
        <Text style={[styles.title, { color: c.text, flex: 1 }]} numberOfLines={1}>{resource.name}</Text>
        <StatusBadge status={resource.status} />
      </View>
      <Text style={{ color: c.textMuted, marginTop: 2 }}>{resource.material?.canonical_name ?? 'Unclassified material'}</Text>
      <View style={[styles.row, { marginTop: spacing.sm, gap: spacing.lg }]}>
        <Meta icon="cube-outline" text={formatQuantity(resource.quantity_available, resource.unit, resource.frequency)} />
        <Meta icon="calendar-outline" text={`Until ${formatDate(resource.availability_end)}`} />
      </View>
    </Card>
  );
}

export function RequirementCard({ requirement }: { requirement: Requirement }) {
  const c = useColors();
  return (
    <Card onPress={() => router.push(`/requirement/${requirement.id}`)} accessibilityLabel={requirement.name}>
      <View style={[styles.row, { justifyContent: 'space-between' }]}>
        <Text style={[styles.title, { color: c.text, flex: 1 }]} numberOfLines={1}>{requirement.name}</Text>
        <StatusBadge status={requirement.status} />
      </View>
      <Text style={{ color: c.textMuted, marginTop: 2 }}>
        {requirement.material?.canonical_name ?? requirement.intended_application?.name ?? 'Any suitable material'}
      </Text>
      <View style={[styles.row, { marginTop: spacing.sm, gap: spacing.lg }]}>
        <Meta icon="cube-outline" text={formatQuantity(requirement.quantity_required, requirement.unit, requirement.frequency)} />
        <Meta icon="calendar-outline" text={`From ${formatDate(requirement.required_from)}`} />
      </View>
    </Card>
  );
}

/** Searchable single-select presented as a bottom sheet (minimal typing on mobile). */
export function SelectField<T>({ label, value, options, onChange, getLabel, getKey, placeholder, searchable = true, hint }: {
  label: string; value: T | null | undefined; options: T[]; onChange: (v: T | null) => void;
  getLabel: (v: T) => string; getKey: (v: T) => string; placeholder?: string; searchable?: boolean; hint?: string;
}) {
  const c = useColors();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const filtered = options.filter((o) => getLabel(o).toLowerCase().includes(query.toLowerCase()));
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={{ color: c.text, fontSize: fontSize.sm, fontWeight: '600', marginBottom: spacing.xs }}>{label}</Text>
      <Pressable onPress={() => setOpen(true)} accessibilityRole="button" accessibilityLabel={label}
        style={[styles.select, { borderColor: c.border, backgroundColor: c.surface }]}>
        <Text style={{ color: value ? c.text : c.textMuted, flex: 1 }}>{value ? getLabel(value) : placeholder ?? 'Select'}</Text>
        <Ionicons name="chevron-down" size={18} color={c.textMuted} />
      </Pressable>
      {hint ? <Text style={{ color: c.textMuted, fontSize: fontSize.sm, marginTop: spacing.xs }}>{hint}</Text> : null}
      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <View style={styles.sheetBackdrop}>
          <View style={[styles.sheet, { backgroundColor: c.background }]}>
            <View style={[styles.row, { justifyContent: 'space-between', marginBottom: spacing.md }]}>
              <Text style={{ color: c.text, fontSize: fontSize.lg, fontWeight: '700' }}>{label}</Text>
              <Button title="Close" variant="ghost" onPress={() => setOpen(false)} />
            </View>
            {searchable ? (
              <TextInput value={query} onChangeText={setQuery} placeholder="Search" placeholderTextColor={c.textMuted}
                style={[styles.select, { borderColor: c.border, color: c.text, marginBottom: spacing.md }]} />
            ) : null}
            <ScrollView keyboardShouldPersistTaps="handled">
              {value ? <Option label="Clear selection" onPress={() => { onChange(null); setOpen(false); }} muted /> : null}
              {filtered.map((o) => (
                <Option key={getKey(o)} label={getLabel(o)} selected={!!value && getKey(value) === getKey(o)}
                  onPress={() => { onChange(o); setOpen(false); setQuery(''); }} />
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function Option({ label, onPress, selected, muted }: { label: string; onPress: () => void; selected?: boolean; muted?: boolean }) {
  const c = useColors();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" style={[styles.option, { borderColor: c.border }]}>
      <Text style={{ color: muted ? c.textMuted : c.text, fontSize: fontSize.md, flex: 1 }}>{label}</Text>
      {selected ? <Ionicons name="checkmark" size={20} color={c.accent} /> : null}
    </Pressable>
  );
}

/** Progress header for multi-step creation flows. */
export function StepHeader({ step, total, title, subtitle }: { step: number; total: number; title: string; subtitle?: string }) {
  const c = useColors();
  return (
    <View style={{ marginBottom: spacing.lg }}>
      <View style={[styles.row, { gap: 4, marginBottom: spacing.md }]}>
        {Array.from({ length: total }).map((_, i) => (
          <View key={i} style={{ flex: 1, height: 4, borderRadius: 2, backgroundColor: i < step ? c.accent : c.surfaceMuted }} />
        ))}
      </View>
      <Text style={{ color: c.textMuted, fontSize: fontSize.sm }}>Step {step} of {total}</Text>
      <Text style={{ color: c.text, fontSize: fontSize.xl, fontWeight: '700', marginTop: 2 }}>{title}</Text>
      {subtitle ? <Text style={{ color: c.textMuted, marginTop: spacing.xs }}>{subtitle}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  title: { fontSize: fontSize.lg, fontWeight: '700', marginTop: 2 },
  select: { minHeight: touchTarget, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.md,
    flexDirection: 'row', alignItems: 'center' },
  sheetBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)', justifyContent: 'flex-end' },
  sheet: { maxHeight: '85%', borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.lg },
  option: { minHeight: touchTarget, flexDirection: 'row', alignItems: 'center', borderBottomWidth: StyleSheet.hairlineWidth },
});
