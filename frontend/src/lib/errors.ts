export function getErrorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'status' in error) {
    const status = (error as { status: number }).status;
    if (status === 403) return "You don't have permission to view this page.";
    if (status === 404) return "This page doesn't exist.";
  }
  return 'Something went wrong. Please try again.';
}
