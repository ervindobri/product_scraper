

class Product {
  final String store;
  final String name;
  final String url;
  final double price;

  /// price normalized to HUF by the backend, for cross-currency sorting
  final double priceHuf;
  final String currency;
  final int score;
  Product({
    required this.store,
    required this.name,
    required this.url,
    required this.price,
    required this.priceHuf,
    required this.currency,
    required this.score,
  });

  
  factory Product.from(Map<String, dynamic> e) {
    return Product(
      name: e['name'] ?? '',
      // the API serializes the store as its integer primary key
      store: '${e['store'] ?? ''}',
      url: e['url'] ?? '',
      price: (e['price'] as num?)?.toDouble() ?? 0.0,
      priceHuf: (e['price_huf'] as num?)?.toDouble() ?? 0.0,
      currency: e['currency'] ?? '',
      score: (e['score'] as num?)?.toInt() ?? 0,
    );
  }

}


class ProductList{
  final int total;
  final List<Product> items;

  ProductList({required this.total, required this.items});


  factory ProductList.from(Map<String, dynamic> json){
    return ProductList(total: json['query']['results_count'], items: (json['products'] as List<dynamic>).map((e) => Product.from(e)).toList());
  }
}