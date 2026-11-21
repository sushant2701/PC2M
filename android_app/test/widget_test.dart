import 'package:flutter_test/flutter_test.dart';
import 'package:pocketdesk_app/main.dart';

void main() {
  test('normalizeLink accepts https links and bare hosts, rejects http/garbage', () {
    expect(normalizeLink('https://a.b.com/#c=ABC'), 'https://a.b.com/#c=ABC');
    expect(normalizeLink('a.b.com'), 'https://a.b.com');
    expect(normalizeLink('http://a.b.com'), isNull);
    expect(normalizeLink(''), isNull);
  });
}
