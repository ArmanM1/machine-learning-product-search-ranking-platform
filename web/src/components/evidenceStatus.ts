export function evidenceStatusPresentation(fixture: boolean) {
  return fixture
    ? { className: 'fixture', label: 'Fixture data' }
    : { className: 'published', label: 'Published evidence' }
}
