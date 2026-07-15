class QueriesList {
  final int totalCount;
  final List<Query> items;

  QueriesList({required this.totalCount, required this.items});
  factory QueriesList.from(Map<String, dynamic> json) {
    return QueriesList(
      totalCount: json['count'] as int? ?? 0,
      items: (json['results'] as List<dynamic>)
          .map((e) => Query.from(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class Query {
  final String query;
  final int resultCount;
  final DateTime? lastSearchedDate;

  Query({
    required this.query,
    required this.resultCount,
    required this.lastSearchedDate,
  });

  factory Query.from(Map<String, dynamic> json) {
    final rawDate = json['last_searched_date'] as String?;
    return Query(
      query: json['query'] ?? '',
      resultCount: json['results_count'] as int? ?? 0,
      lastSearchedDate: rawDate == null ? null : DateTime.parse(rawDate),
    );
  }
}
