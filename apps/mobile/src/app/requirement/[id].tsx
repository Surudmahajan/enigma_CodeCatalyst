import { useLocalSearchParams } from 'expo-router';
import { Text, View } from 'react-native';

import { MatchCard } from '@/components/domain';
import { ListingActions } from '@/components/listing-actions';
import { Body, Card, Chip, EmptyState, KeyValue, Notice, QueryState, Screen, SectionHeader, StatusBadge, Title } from '@/components/ui';
import { formatDate, formatMoney, formatNumber, formatQuantity } from '@/lib/format';
import { useMatches, useRequirement } from '@/lib/queries';
import { fontSize, spacing, useColors } from '@/theme';

export default function RequirementDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const c = useColors();
  const requirement = useRequirement(id);
  const matches = useMatches({ requirement_id: id });
  const q = requirement.data;

  return (
    <Screen refreshing={requirement.isRefetching} onRefresh={() => { requirement.refetch(); matches.refetch(); }}>
      <QueryState query={requirement}>
        {q ? (
          <>
            <Title sub={q.intended_application ? `For ${q.intended_application.name}` : q.material?.canonical_name}>{q.name}</Title>
            <View style={{ marginBottom: spacing.md }}><StatusBadge status={q.status} /></View>
            {q.description ? <Body style={{ marginBottom: spacing.md }}>{q.description}</Body> : null}
            <Card>
              <KeyValue icon="cube-outline" label="Demand" value={formatQuantity(q.quantity_required, q.unit, q.frequency)} />
              <KeyValue icon="calendar-outline" label="Needed" value={`${formatDate(q.required_from)} → ${formatDate(q.required_until)}`} />
              <KeyValue icon="layers-outline" label="Material" value={q.material?.canonical_name ?? 'Any suitable'} />
              <KeyValue icon="location-outline" label="Facility" value={`${q.facility.name}, ${q.facility.location.city}`} />
              <KeyValue icon="navigate-outline" label="Max distance" value={q.max_transport_distance_km ? `${formatNumber(q.max_transport_distance_km)} km` : 'No limit'} />
              <KeyValue icon="construct-outline" label="Can process" value={q.processing_capabilities.join(', ') || 'None declared'} />
              <KeyValue icon="cash-outline" label="Current price" value={q.virgin_material_price_per_unit ? `${formatMoney(q.virgin_material_price_per_unit, q.currency)}/${q.unit}` : '—'} />
            </Card>

            <SectionHeader title="Technical constraints" />
            {q.property_constraints.length ? q.property_constraints.map((k) => (
              <Card key={k.id}>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text style={{ color: c.text, fontWeight: '700', fontSize: fontSize.md }}>{k.property_name}</Text>
                  <Chip label={k.importance.toLowerCase()} tone={k.importance === 'REQUIRED' ? 'danger' : k.importance === 'PREFERRED' ? 'warning' : 'info'} />
                </View>
                <Body muted>
                  {k.min_value !== null && k.min_value !== undefined ? `≥ ${formatNumber(k.min_value, 3)} ` : ''}
                  {k.max_value !== null && k.max_value !== undefined ? `≤ ${formatNumber(k.max_value, 3)} ` : ''}{k.unit ?? ''}
                </Body>
              </Card>
            )) : <Notice>No technical constraints. Adding them improves match precision and confidence.</Notice>}

            <SectionHeader title="Potential providers" />
            <QueryState query={matches}>
              {matches.data?.length ? matches.data.map((m) => <MatchCard key={m.id} match={m} />)
                : <EmptyState icon="search-outline" title="No providers found yet"
                    message={q.status === 'ACTIVE' ? 'You will be notified when a compatible resource is published.' : 'Publish this requirement to start matching.'} />}
            </QueryState>

            <SectionHeader title="Lifecycle" />
            <ListingActions kind="requirements" id={q.id} status={q.status} allowed={q.allowed_transitions} />
          </>
        ) : null}
      </QueryState>
    </Screen>
  );
}
