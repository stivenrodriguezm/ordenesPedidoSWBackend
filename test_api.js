const http = require('http');

http.get('http://localhost:8000/api/pedidos-telas/', (res) => {
  let data = '';
  res.on('data', (chunk) => { data += chunk; });
  res.on('end', () => {
    try {
      const parsed = JSON.parse(data);
      console.log(JSON.stringify(parsed.results ? parsed.results.slice(0, 3) : parsed.slice(0, 3), null, 2));
    } catch (e) {
      console.log("Error parsing JSON:", e.message);
    }
  });
}).on('error', (err) => {
  console.log("Error: " + err.message);
});
