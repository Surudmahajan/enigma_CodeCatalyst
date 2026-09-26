import { useState } from 'react';
import { View } from 'react-native';

import { MatchCard } from '@/components/domain';
import { Chip, EmptyState, QueryState, Screen, Segmented, Title } from '@/components/ui';
import { useAuth, useMembership } from '@/lib/auth-store';
import { useMatches } from '@/lib/queries';
import { spacing } from '@/theme';

export default function Matches() {
  const membership = useMembership();
  const { viewMode, setViewMode } = useAuth();
  const [includeClosed, setIncludeClosed] = useState(false);
  const [hiddenOnly, setHiddenOnly] = useState(false);
  const matches = useMatches({ side: viewMode === 'PROVIDER' ? 'provider' : 'demander', include_closed: includeClosed });
  const list = (matches.data ?? []).filter((m) => !hiddenOnly || m.is_hidden_match);

  return (
    <Screen refreshing={matches.isRefetching} onRefresh={() => matches.refetch()}>
      <Title sub="Discovered by the matching engine and ranked by opportunity score">Opportunities</Title>
      {membership?.operating_mode === 'BOTH' ? (
        <Segmented value={viewMode} onChange={setViewMode}
          options={[{ value: 'PROVIDER', label: 'As provider' }, { value: 'DEMANDER', label: 'As demander' }]} />
      ) : null}
      <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md }}>
        <Chip label="Hidden matches" selected={hiddenOnly} onPress={() => setHiddenOnly(!hiddenOnly)} />
        <Chip label="Include closed" selected={includeClosed} onPress={() => setIncludeClosed(!includeClosed)} />
      </View>
      <QueryState query={matches}>
        {list.length ? list.map((m) => <MatchCard key={m.id} match={m} />) : (
          <EmptyState icon="git-compare-outline" title="No opportunities to show"
            message="Matches appear automatically when an active listing fits another organization's needs. Pull to refresh." />
        )}
      </QueryState>
    </Screen>
  );
}
