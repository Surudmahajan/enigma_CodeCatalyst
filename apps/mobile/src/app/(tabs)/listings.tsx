import { router } from 'expo-router';

import { RequirementCard, ResourceCard } from '@/components/domain';
import { Button, EmptyState, QueryState, Screen, Segmented, Title } from '@/components/ui';
import { useAuth, useCan, useMembership } from '@/lib/auth-store';
import { useRequirements, useResources } from '@/lib/queries';

export default function Listings() {
  const membership = useMembership();
  const { viewMode, setViewMode } = useAuth();
  const canEdit = useCan('MANAGE_LISTINGS');
  const resources = useResources();
  const requirements = useRequirements();
  const provider = viewMode === 'PROVIDER';
  const query = provider ? resources : requirements;

  return (
    <Screen refreshing={query.isRefetching} onRefresh={() => query.refetch()}>
      <Title sub={provider ? 'What your organization can provide' : 'What your organization needs'}>
        {provider ? 'Resources' : 'Requirements'}
      </Title>
      {membership?.operating_mode === 'BOTH' ? (
        <Segmented value={viewMode} onChange={setViewMode}
          options={[{ value: 'PROVIDER', label: 'Resources' }, { value: 'DEMANDER', label: 'Requirements' }]} />
      ) : null}
      {canEdit ? (
        <Button title={provider ? 'Add resource' : 'Add requirement'} icon="add-circle-outline"
          onPress={() => router.push(provider ? '/resource/new' : '/requirement/new')} style={{ marginBottom: 16 }} />
      ) : null}
      <QueryState query={query}>
        {provider
          ? resources.data?.length
            ? resources.data.map((r) => <ResourceCard key={r.id} resource={r} />)
            : <EmptyState icon="cube-outline" title="No active resources yet"
                message="List a by-product, residue, surplus material or energy stream to discover who can use it." />
          : requirements.data?.length
            ? requirements.data.map((r) => <RequirementCard key={r.id} requirement={r} />)
            : <EmptyState icon="clipboard-outline" title="No requirements yet"
                message="Describe a material you need — SYMBIO also finds differently named materials that fit." />}
      </QueryState>
    </Screen>
  );
}
