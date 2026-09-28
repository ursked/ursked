// The same rule the API applies to every password (8+ characters, upper and
// lower case, a digit: backend app/schemas/user.validate_password_strength),
// so a form can say what is wrong before the server has to. My Profile used to
// accept 6 characters here and then show the server's rejection.
export function passwordProblem(pw: string): string | null {
  if (pw.length < 8) return 'At least 8 characters.';
  if (!/[A-Z]/.test(pw)) return 'Include an uppercase letter.';
  if (!/[a-z]/.test(pw)) return 'Include a lowercase letter.';
  if (!/\d/.test(pw)) return 'Include a digit.';
  return null;
}
