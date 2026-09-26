import { Text } from 'react-native';

import { Body, Card, KeyValue, Notice, QueryState, Screen, SectionHeader, Segmented, Title } from '@/components/ui';
import { useAuth } from '@/lib/auth-store';
import { formatMoney, formatNumber } from '@/lib/format';
import { useImpact } from '@/lib/queries';
import { fontSize, useColors } from '@/theme';

const METRIC_LABEL: Record<string, string> = {
  WASTE_DIVERTED: 'Waste diverted', VIRGIN_MATERIAL_AVOIDED: 'Virgin material avoided', TRANSPORT_EMISSIONS: 'Transport emissions',
  PROCESSING_EMISSIONS: 'Processing emissions', NET_CO2E: 'Net CO₂e benefit', ECONOMIC_VALUE: 'Economic value', ENERGY_RECOVERED: 'Energy recovered',
};
const SOURCE_LABEL: Record<string, string> = { SYSTEM_ESTIMATE: 'estimated', USER_INPUT: 'reported', VERIFIED_OUTCOME: 'verified' };

/** Potential (from open opportunities) vs realized (from completed exchanges), with assumptions visible. */
export default function Impact() {
  const c = useColors();
  const impact = useImpact();
  const { viewMode, setViewMode } = useAuth();
  const side = viewMode === 'PROVIDER' ? 'as_provider' : 'as_demander';
  const d = impact.data;

  return (
    <Screen refreshing={impact.isRefetching} onRefresh={() => impact.refetch()}>
      <Title sub="Transparent, versioned estimates — potential is not the same as realized.">Impact</Title>
      <Segmented value={viewMode} onChange={setViewMode}
        options={[{ value: 'PROVIDER', label: 'As provider' }, { value: 'DEMANDER', label: 'As demander' }]} />
      <QueryState query={impact}>
        {d ? (
          <>
            <SectionHeader title="Potential (per month)" />
            <Card>
              <KeyValue icon="git-compare-outline" label="Open opportunities" value={String(d.potential[side].opportunities)} />
              <KeyValue icon="trash-bin-outline" label="Waste divertable" value={`${formatNumber(d.potential[side].waste_divertable_t_per_month)} t`} />
              <KeyValue icon="leaf-outline" label="Virgin material substitutable" value={`${formatNumber(d.potential[side].virgin_substitutable_t_per_month)} t`} />
              <KeyValue icon="cloud-outline" label="Net CO₂e (where assessed)"
                value={d.potential[side].with_co2e_estimate ? `${formatNumber(d.potential[side].net_co2e_kg_per_month)} kg` : 'Not assessed'} />
              {d.potential[side].economic_value_per_month_connected !== undefined ? (
                <KeyValue icon="cash-outline" label="Economic value (connected)" value={formatMoney(d.potential[side].economic_value_per_month_connected)} />
              ) : null}
              <Body muted>{d.potential[side].label}</Body>
            </Card>
            {d.potential[side].uses_demo_factors ? <Notice tone="warning">CO₂e figures use illustrative demo factors.</Notice> : null}

            <SectionHeader title={`Realized · ${d.realized.completed_exchanges} completed exchange(s)`} />
            {Object.keys(d.realized[side]).length ? (
              <Card>
                {Object.entries(d.realized[side]).map(([metric, v]) => (
                  <KeyValue key={metric} label={METRIC_LABEL[metric] ?? metric}
                    value={`${v.unit === 'INR' ? formatMoney(v.total) : `${formatNumber(v.total)} ${v.unit}`} · ${Object.keys(v.by_source).map((s) => SOURCE_LABEL[s] ?? s).join(', ')}`} />
                ))}
              </Card>
            ) : <Notice>No completed exchanges yet. Impact is recorded when an exchange is marked completed.</Notice>}

            <SectionHeader title="Methodology" />
            <Card>
              <Text style={{ color: c.text, fontSize: fontSize.sm }}>{d.methodology.economic} · {d.methodology.environmental}</Text>
              <Body muted>{d.methodology.note}</Body>
            </Card>
          </>
        ) : null}
      </QueryState>
    </Screen>
  );
}
