'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { CustomFieldConfig, CustomFieldDefinition, CustomFieldValue } from '@/types';

// Company-defined employee fields, shared by the employee form, the detail
// panel, the directory table and My Profile. The definitions come back already
// filtered to what the signed-in user may see; values come with each record.

export const DEFAULT_EMPLOYEE_NUMBER_LABEL = 'Personnel #';

export const VISIBILITY_LABELS: Record<CustomFieldDefinition['visibility'], string> = {
  hr_only: 'HR only',
  managers: 'HR and the employee’s managers',
  employee_view: 'Also the employee (read-only)',
  employee_edit: 'Also the employee, who can edit it',
};

export const TYPE_LABELS: Record<CustomFieldDefinition['field_type'], string> = {
  text: 'Text',
  number: 'Number',
  date: 'Date',
  select: 'List of options',
  boolean: 'Yes / no',
};

export function useEmployeeFieldConfig(includeArchived = false) {
  return useQuery<CustomFieldConfig>({
    queryKey: ['employee-field-config', includeArchived],
    queryFn: () => api.getEmployeeFieldConfig(includeArchived),
    staleTime: 60_000,
  });
}

/** The company's name for Personnel # (e.g. "Badge no."). */
export function useEmployeeNumberLabel(): string {
  const { data } = useEmployeeFieldConfig();
  return data?.employee_number_label || DEFAULT_EMPLOYEE_NUMBER_LABEL;
}

export function formatCustomValue(def: CustomFieldDefinition, value: CustomFieldValue | undefined): string {
  if (value === null || value === undefined || value === '') return '';
  if (def.field_type === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
}

interface InputProps {
  def: CustomFieldDefinition;
  value: CustomFieldValue | undefined;
  onChange: (value: CustomFieldValue) => void;
  disabled?: boolean;
  id?: string;
}

const inputClass =
  'w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none text-sm disabled:bg-gray-50 disabled:text-gray-500';

/** One input for a custom field, by type. Empty means "no value" (null). */
export function CustomFieldInput({ def, value, onChange, disabled, id }: InputProps) {
  const inputId = id || `cf-${def.key}`;
  const str = value === null || value === undefined ? '' : String(value);
  let control: React.ReactNode;
  if (def.field_type === 'boolean') {
    control = (
      <select
        id={inputId}
        value={value === true ? 'true' : value === false ? 'false' : ''}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value === 'true')}
        disabled={disabled}
        className={`${inputClass} bg-white`}
      >
        <option value="">Not set</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  } else if (def.field_type === 'select') {
    control = (
      <select
        id={inputId}
        value={str}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={disabled}
        className={`${inputClass} bg-white`}
      >
        <option value="">Not set</option>
        {def.options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
        {str && !def.options.includes(str) && <option value={str}>{str} (no longer an option)</option>}
      </select>
    );
  } else {
    control = (
      <input
        id={inputId}
        type={def.field_type === 'number' ? 'number' : def.field_type === 'date' ? 'date' : 'text'}
        step={def.field_type === 'number' ? 'any' : undefined}
        value={str}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
        disabled={disabled}
        maxLength={def.field_type === 'text' ? 500 : undefined}
        className={inputClass}
      />
    );
  }
  return (
    <div>
      <label htmlFor={inputId} className="block text-sm font-medium text-gray-700 mb-1">
        {def.label}
        {def.is_required && <span className="text-red-600"> *</span>}
        {def.is_sensitive && <span className="ml-2 text-xs font-normal text-amber-700">Sensitive</span>}
      </label>
      {control}
      {def.help_text && <p className="mt-1 text-xs text-gray-500">{def.help_text}</p>}
    </div>
  );
}
