import { User, RoleCode } from '@/types';

const ROLE_DISPLAY_NAMES: Record<string, string> = {
  tenant_admin: 'Administrator',
  hr: 'HR',
  finance: 'Finance',
  manager: 'Manager',
  leave_approver: 'Leave Approver',
  schedule_editor: 'Schedule Editor',
  employee: 'Employee',
};

const ROLE_PRIORITY: string[] = [
  'tenant_admin',
  'hr',
  'finance',
  'manager',
  'leave_approver',
  'schedule_editor',
  'employee',
];

export function hasRole(user: User, roleCode: string): boolean {
  return user.roles?.some((ur) => ur.role.code === roleCode) ?? false;
}

export function hasAnyRole(user: User, roleCodes: string[]): boolean {
  if (!user.roles) return false;
  const userCodes: Set<string> = new Set(user.roles.map((ur) => ur.role.code));
  return roleCodes.some((code) => userCodes.has(code));
}

export function getRoleCodes(user: User): string[] {
  return user.roles?.map((ur) => ur.role.code) ?? [];
}

export function getPrimaryRole(user: User): string {
  if (user.primary_role) {
    return ROLE_DISPLAY_NAMES[user.primary_role] ?? user.primary_role.replace(/_/g, ' ');
  }
  const codes = getRoleCodes(user);
  for (const p of ROLE_PRIORITY) {
    if (codes.includes(p)) {
      return ROLE_DISPLAY_NAMES[p] ?? p;
    }
  }
  return 'Employee';
}

export function getRoleNames(user: User): string {
  if (!user.roles || user.roles.length === 0) return 'Employee';
  return user.roles
    .map((ur) => ROLE_DISPLAY_NAMES[ur.role.code] ?? ur.role.name)
    .join(', ');
}
