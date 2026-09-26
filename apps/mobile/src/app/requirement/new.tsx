import type { ApplicationType, Facility, MaterialSummary, PropertyDefinition } from '@symbio/shared-types';
import { FREQUENCIES, UNITS, requirementSchema, splitList } from '@symbio/validation';
import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Alert, Text, View } from 'react-native';

import { SelectField, StepHeader } from '@/components/domain';
import { Button, Card, Chip, KeyValue, Notice, Screen, TextField } from '@/components/ui';
import { errorMessage } from '@/lib/api';
import { addDays, formatDate, formatQuantity, today } from '@/lib/format';
import { useApplications, useCreateRequirement, useFacilities, useMaterials, useProperties } from '@/lib/queries';
import { pickDocument, type PickedFile, uploadDocument } from '@/lib/upload';
import { spacing, useColors } from '@/theme';

type Importance = 'REQUIRED' | 'PREFERRED' | 'OPTIONAL';
type ConstraintRow = { key: string; min: string; max: string; importance: Importance };
const TOTAL = 9;

/** Multi-step requirement creation — the demander-side equivalent of the resource flow. */
export default function NewRequirement() {
  const c = useColors();
  const [step, setStep] = useState(1);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const materials = useMaterials('');
  const applications = useApplications();
  const facilities = useFacilities();
  const properties = useProperties();
  const create = useCreateRequirement();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [material, setMaterial] = useState<MaterialSummary | null>(null);
  const [application, setApplication] = useState<ApplicationType | null>(null);
  const [quantity, setQuantity] = useState('');
  const [unit, setUnit] = useState<(typeof UNITS)[number]>('tonne');
  const [frequency, setFrequency] = useState<(typeof FREQUENCIES)[number]>('MONTH');
  const [facility, setFacility] = useState<Facility | null>(null);
  const [maxDistance, setMaxDistance] = useState('');
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(addDays(365));
  const [rows, setRows] = useState<ConstraintRow[]>([]);
  const [capabilities, setCapabilities] = useState('');
  const [virginPrice, setVirginPrice] = useState('');
  const [file, setFile] = useState<PickedFile | null>(null);

  useEffect(() => {
    if (!facility && facilities.data?.length) setFacility(facilities.data[0]);
  }, [facilities.data, facility]);
  const propertyByKey = useMemo(() => new Map((properties.data ?? []).map((p) => [p.key, p])), [properties.data]);

  const form = { name, description, material_id: material?.id ?? null, intended_application_id: application?.id ?? null,
    quantity, unit, frequency, facility_id: facility?.id ?? '', window_start: start, window_end: end,
    max_transport_distance_km: maxDistance, processing_capabilities: capabilities, virgin_material_price_per_unit: virginPrice };
  const STEP_FIELDS: Record<number, string[]> = { 1: ['name'], 2: ['quantity'], 3: ['facility_id', 'max_transport_distance_km'],
    4: ['window_start', 'window_end'], 6: ['virgin_material_price_per_unit'] };

  const next = () => {
    const fieldErrors: Record<string, string> = {};
    const result = requirementSchema.safeParse(form);
    if (!result.success) result.error.issues.forEach((i) => { fieldErrors[String(i.path[0])] ??= i.message; });
    if (step === 1 && !material && !application) fieldErrors.name ??= 'Choose a material or what you need it for (or both).';
    if (step === 5) rows.forEach((r, i) => {
      if (!r.key) fieldErrors[`row${i}`] = 'Choose a property';
      else if (!r.min && !r.max) fieldErrors[`row${i}`] = 'Set a minimum or maximum';
      else if (r.min && r.max && Number(r.min) > Number(r.max)) fieldErrors[`row${i}`] = 'Minimum cannot exceed maximum';
    });
    const relevant = Object.fromEntries(Object.entries(fieldErrors).filter(([k]) =>
      (STEP_FIELDS[step] ?? []).includes(k) || (step === 5 && k.startsWith('row'))));
    setErrors(relevant);
    if (!Object.keys(relevant).length) setStep((s) => Math.min(TOTAL, s + 1));
  };

  const submit = async (publish: boolean) => {
    try {
      const requirement = await create.mutateAsync({
        facility_id: facility!.id, currency: 'INR', material_id: material?.id ?? null, intended_application_id: application?.id ?? null,
        name: name.trim(), description: description || null, quantity_required: quantity, unit, frequency,
        required_from: start, required_until: end || null, max_transport_distance_km: maxDistance || null,
        processing_capabilities: splitList(capabilities), virgin_material_price_per_unit: virginPrice || null,
        property_constraints: rows.map((r) => ({ property_key: r.key, min_value: r.min || null, max_value: r.max || null,
          importance: r.importance })),
        publish,
      });
      if (file) await uploadDocument(file, { requirement_id: requirement.id }).catch((e) => Alert.alert('Document not uploaded', errorMessage(e)));
      Alert.alert(publish ? 'Requirement published' : 'Draft saved',
        publish ? 'SYMBIO is now searching for compatible providers, including differently named materials.' : 'Publish it when ready.');
      router.replace(`/requirement/${requirement.id}`);
    } catch (e) {
      Alert.alert('Could not save the requirement', errorMessage(e));
    }
  };

  const updateRow = (i: number, patch: Partial<ConstraintRow>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  return (
    <Screen>
      {step === 1 ? (
        <>
          <StepHeader step={1} total={TOTAL} title="What do you need?"
            subtitle="Tell us the material, what it's for, or both. 'What it's for' uncovers hidden matches." />
          <TextField label="Name" value={name} onChangeText={setName} placeholder="e.g. Aggregate for road sub-base" error={errors.name} />
          <TextField label="Description (optional)" value={description} onChangeText={setDescription} multiline />
          <SelectField label="Material (optional)" value={material} options={materials.data ?? []} onChange={setMaterial}
            getKey={(m) => m.id} getLabel={(m) => `${m.canonical_name} · ${m.category}`} placeholder="Any suitable material" />
          <SelectField label="Intended application" value={application} options={applications.data ?? []} onChange={setApplication}
            getKey={(a) => a.id} getLabel={(a) => a.name} placeholder="What will you use it for?"
            hint="Any material known to serve this application can be suggested — e.g. slag or fly ash for cement blending." />
        </>
      ) : null}

      {step === 2 ? (
        <>
          <StepHeader step={2} total={TOTAL} title="How much?" subtitle="Several providers can each cover part of your demand." />
          <TextField label="Quantity required" value={quantity} onChangeText={setQuantity} keyboardType="decimal-pad" error={errors.quantity} />
          <Text style={{ color: c.text, fontWeight: '600', marginBottom: spacing.sm }}>Unit</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.lg }}>
            {UNITS.map((u) => <Chip key={u} label={u} selected={unit === u} onPress={() => setUnit(u)} />)}
          </View>
          <Text style={{ color: c.text, fontWeight: '600', marginBottom: spacing.sm }}>Frequency</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
            {FREQUENCIES.map((f) => <Chip key={f} label={f === 'ONE_TIME' ? 'One-time' : `Per ${f.toLowerCase()}`}
              selected={frequency === f} onPress={() => setFrequency(f)} />)}
          </View>
        </>
      ) : null}

      {step === 3 ? (
        <>
          <StepHeader step={3} total={TOTAL} title="Where?" subtitle="Receiving facility and how far you'd transport from." />
          <SelectField label="Receiving facility" value={facility} options={facilities.data ?? []} onChange={setFacility} searchable={false}
            getKey={(f) => f.id} getLabel={(f) => `${f.name} · ${f.location.city}`} />
          <TextField label="Maximum transport distance, km (optional)" value={maxDistance} onChangeText={setMaxDistance}
            keyboardType="decimal-pad" error={errors.max_transport_distance_km}
            hint="A hard limit: providers farther away are excluded. Leave blank to see distant options with lower scores." />
        </>
      ) : null}

      {step === 4 ? (
        <>
          <StepHeader step={4} total={TOTAL} title="When do you need it?" />
          <TextField label="Required from (YYYY-MM-DD)" value={start} onChangeText={setStart} error={errors.window_start} />
          <TextField label="Required until (YYYY-MM-DD, blank = open-ended)" value={end} onChangeText={setEnd} error={errors.window_end} />
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
            <Chip label="6 months" onPress={() => setEnd(addDays(182))} />
            <Chip label="1 year" onPress={() => setEnd(addDays(365))} />
            <Chip label="Open-ended" onPress={() => setEnd('')} />
          </View>
        </>
      ) : null}

      {step === 5 ? (
        <>
          <StepHeader step={5} total={TOTAL} title="Technical constraints"
            subtitle="REQUIRED limits exclude incompatible materials; PREFERRED and OPTIONAL affect the score." />
          {rows.map((row, i) => (
            <Card key={i}>
              <SelectField<PropertyDefinition> label="Property" value={propertyByKey.get(row.key) ?? null} options={properties.data ?? []}
                getKey={(p) => p.key} getLabel={(p) => `${p.name}${p.unit ? ` (${p.unit})` : ''}`}
                onChange={(p) => updateRow(i, { key: p?.key ?? '' })} />
              <View style={{ flexDirection: 'row', gap: spacing.md }}>
                <View style={{ flex: 1 }}><TextField label="Minimum" value={row.min} keyboardType="decimal-pad" onChangeText={(v) => updateRow(i, { min: v })} /></View>
                <View style={{ flex: 1 }}><TextField label="Maximum" value={row.max} keyboardType="decimal-pad" onChangeText={(v) => updateRow(i, { max: v })} /></View>
              </View>
              <View style={{ flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.sm }}>
                {(['REQUIRED', 'PREFERRED', 'OPTIONAL'] as const).map((imp) => (
                  <Chip key={imp} label={imp.toLowerCase()} selected={row.importance === imp} onPress={() => updateRow(i, { importance: imp })} />
                ))}
              </View>
              {errors[`row${i}`] ? <Notice tone="danger">{errors[`row${i}`]}</Notice> : null}
              <Button title="Remove" variant="ghost" onPress={() => setRows(rows.filter((_, j) => j !== i))} />
            </Card>
          ))}
          <Button title="Add constraint" icon="add" variant="secondary"
            onPress={() => setRows([...rows, { key: '', min: '', max: '', importance: 'REQUIRED' }])} />
        </>
      ) : null}

      {step === 6 ? (
        <>
          <StepHeader step={6} total={TOTAL} title="Processing & economics" subtitle="Helps assess whether a by-product is practical for you." />
          <TextField label="Processing you can do (comma separated)" value={capabilities} onChangeText={setCapabilities}
            placeholder="crushing, screening, grinding" />
          <TextField label="What you pay today for the virgin material, per unit (optional)" value={virginPrice}
            onChangeText={setVirginPrice} keyboardType="decimal-pad" error={errors.virgin_material_price_per_unit}
            hint="Used only to estimate potential savings; never shown to providers before you connect." />
        </>
      ) : null}

      {step === 7 ? (
        <>
          <StepHeader step={7} total={TOTAL} title="Specification document" subtitle="Optional: your material specification or tender extract." />
          {file ? <Card><KeyValue icon="document-attach-outline" label={file.name} value={`${Math.round((file.size ?? 0) / 1024)} KB`} /></Card> : null}
          <Button title={file ? 'Choose a different file' : 'Choose file'} icon="attach" variant="secondary" onPress={async () => setFile(await pickDocument())} />
        </>
      ) : null}

      {step === 8 ? (
        <>
          <StepHeader step={8} total={TOTAL} title="Review" />
          <Card>
            <KeyValue label="Name" value={name} />
            <KeyValue label="Material" value={material?.canonical_name ?? 'Any suitable'} />
            <KeyValue label="Application" value={application?.name ?? '—'} />
            <KeyValue label="Quantity" value={formatQuantity(quantity || 0, unit, frequency)} />
            <KeyValue label="Facility" value={facility?.name ?? '—'} />
            <KeyValue label="Max distance" value={maxDistance ? `${maxDistance} km` : 'No limit'} />
            <KeyValue label="Window" value={`${formatDate(start)} → ${formatDate(end || null)}`} />
            <KeyValue label="Constraints" value={String(rows.length)} />
          </Card>
        </>
      ) : null}

      {step === 9 ? (
        <>
          <StepHeader step={9} total={TOTAL} title="Publish" subtitle="Publishing adds it to the common database and starts matching." />
          <Button title="Publish requirement" icon="rocket-outline" onPress={() => submit(true)} loading={create.isPending} />
          <View style={{ height: spacing.md }} />
          <Button title="Save as draft" variant="secondary" onPress={() => submit(false)} disabled={create.isPending} />
        </>
      ) : null}

      <View style={{ flexDirection: 'row', gap: spacing.md, marginTop: spacing.xl }}>
        {step > 1 ? <Button title="Back" variant="secondary" onPress={() => setStep(step - 1)} style={{ flex: 1 }} /> : null}
        {step < TOTAL ? <Button title="Next" onPress={next} style={{ flex: 1 }} /> : null}
      </View>
    </Screen>
  );
}
