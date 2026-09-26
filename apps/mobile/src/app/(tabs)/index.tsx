import { router } from 'expo-router';
import { View } from 'react-native';

import { MatchCard } from '@/components/domain';
import { Button, Chip, EmptyState, Notice, QueryState, Screen, SectionHeader, Segmented, Stat, Title } from '@/components/ui';
import { useAuth, useMembership } from '@/lib/auth-store';
import { formatNumber } from '@/lib/format';
import { useDashboard, useMatches } from '@/lib/queries';
import { spacing } from '@/theme';

/** Provider and Demander dashboards; organizations that are Both switch with the segmented control. */
export default function Dashboard() {
  const membership = useMembership();
  const { viewMode, setViewMode } = useAuth();
  const dashboard = useDashboard();
  const side = viewMode === 'PROVIDER' ? 'provider' : 'demander';
  const matches = useMatches({ side });
  const d = dashboard.data;
  const isBoth = membership?.operating_mode === 'BOTH';

  return (
    <Screen refreshing={dashboard.isRefetching} onRefresh={() => { dashboard.refetch(); matches.refetch(); }}>
      <Title sub={membership?.verification_status === 'VERIFIED' ? 'Verified organization' : 'Verification pending'}>
        {membership?.organization_name ?? 'SYMBIO'}
      </Title>
      {isBoth ? (
        <Segmented value={viewMode} onChange={setViewMode}
          options={[{ value: 'PROVIDER', label: 'Provider' }, { value: 'DEMANDER', label: 'Demander' }]} />
      ) : null}
      <QueryState query={dashboard}>
        {d ? (
          viewMode === 'PROVIDER' ? (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md }}>
              <Stat icon="cube-outline" label="Active resources" value={d.provider.active_resources} onPress={() => router.push('/listings')} />
              <Stat icon="git-compare-outline" label="Potential matches" value={d.provider.potential_matches} onPress={() => router.push('/matches')} />
              <Stat icon="person-add-outline" label="Connection requests" value={d.provider.connection_requests} onPress={() => router.push('/messages')} />
              <Stat icon="swap-horizontal-outline" label="Active exchanges" value={d.provider.active_exchanges} onPress={() => router.push('/more')} />
              <Stat icon="leaf-outline" label="Potential diversion (t/month)"
                value={formatNumber(d.provider.impact.potential_waste_divertable_t_per_month)} onPress={() => router.push('/impact')} />
              <Stat icon="checkmark-done-outline" label="Diverted so far (t)"
                value={formatNumber(d.provider.impact.realized_waste_diverted_t)} onPress={() => router.push('/impact')} />
            </View>
          ) : (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md }}>
              <Stat icon="clipboard-outline" label="Active requirements" value={d.demander.active_requirements} onPress={() => router.push('/listings')} />
              <Stat icon="business-outline" label="Potential providers" value={d.demander.potential_providers} onPress={() => router.push('/matches')} />
              <Stat icon="person-add-outline" label="Connection requests" value={d.demander.connection_requests} onPress={() => router.push('/messages')} />
              <Stat icon="swap-horizontal-outline" label="Active exchanges" value={d.demander.active_exchanges} onPress={() => router.push('/more')} />
              <Stat icon="leaf-outline" label="Substitutable (t/month)"
                value={formatNumber(d.demander.resource_savings.potential_virgin_substitutable_t_per_month)} onPress={() => router.push('/impact')} />
              <Stat icon="checkmark-done-outline" label="Virgin material avoided (t)"
                value={formatNumber(d.demander.resource_savings.realized_virgin_material_avoided_t)} onPress={() => router.push('/impact')} />
            </View>
          )
        ) : null}
      </QueryState>

      <SectionHeader title={viewMode === 'PROVIDER' ? 'Who can use your resources' : 'Who can supply you'}
        action={<Chip label="See all" onPress={() => router.push('/matches')} />} />
      <QueryState query={matches}>
        {matches.data?.length ? (
          matches.data.slice(0, 3).map((m) => <MatchCard key={m.id} match={m} />)
        ) : (
          <EmptyState icon="search-outline" title="No opportunities yet"
            message={viewMode === 'PROVIDER' ? 'Publish a resource and SYMBIO will look for organizations that can use it.'
              : 'Publish a requirement and SYMBIO will look for providers.'}
            action={<Button title={viewMode === 'PROVIDER' ? 'Add a resource' : 'Add a requirement'} icon="add"
              onPress={() => router.push(viewMode === 'PROVIDER' ? '/resource/new' : '/requirement/new')} />} />
        )}
      </QueryState>
      <Notice>Scores indicate potential opportunities based on the data provided — they are not guarantees.</Notice>
    </Screen>
  );
}
