<?php
/**
 * siri-proxy.php : relais serveur vers le flux temps réel SIRI Aix-en-Bus (optionnel).
 *
 * ⚠ NON TESTÉ : je n'ai pas pu joindre le serveur SIRI depuis mon environnement.
 *   Le format de la requête SOAP ci-dessous est le format SIRI standard ; il faut le valider avec l'outil
 *   https://transport.data.gouv.fr/tools/siri-querier (endpoint https://siri.lametropolemobilite.fr/KPA,
 *   RequestorRef « open-data ») et ajuster si besoin. Voir LISEZ-MOI.md.
 *
 * Pourquoi un relais : le flux limite à 10-20 requêtes/minute au total, et un navigateur ne peut pas
 * l'appeler directement (CORS + POST SOAP). Ce script met la réponse en cache 45 s par arrêt.
 * Réponse : {"ok":true,"ts":"…","visits":[{"aimed":"…","expected":"…","cancelled":false}]}
 */
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

const ENDPOINT = 'https://siri.lametropolemobilite.fr/KPA';
const REQUESTOR = 'open-data';
const CACHE_SECONDS = 45;

$ref = $_GET['ref'] ?? '';
if (!preg_match('/^AIX-[0-9]{4,6}$/', $ref)) { http_response_code(400); echo '{"ok":false}'; exit; }

$cache = sys_get_temp_dir() . '/siri_' . $ref . '.json';
if (is_file($cache) && time() - filemtime($cache) < CACHE_SECONDS) { readfile($cache); exit; }

$now = gmdate('Y-m-d\TH:i:s\Z');
$body = '<?xml version="1.0" encoding="UTF-8"?>'
  . '<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/"><S:Body>'
  . '<sw:GetStopMonitoring xmlns:sw="http://wsdl.siri.org.uk" xmlns:siri="http://www.siri.org.uk/siri">'
  . '<ServiceRequestInfo><siri:RequestTimestamp>' . $now . '</siri:RequestTimestamp>'
  . '<siri:RequestorRef>' . REQUESTOR . '</siri:RequestorRef><siri:MessageIdentifier>luynes-' . uniqid() . '</siri:MessageIdentifier></ServiceRequestInfo>'
  . '<Request version="2.0"><siri:RequestTimestamp>' . $now . '</siri:RequestTimestamp>'
  . '<siri:MessageIdentifier>luynes-' . uniqid() . '</siri:MessageIdentifier>'
  . '<siri:MonitoringRef>' . htmlspecialchars($ref) . '</siri:MonitoringRef></Request>'
  . '<RequestExtension/></sw:GetStopMonitoring></S:Body></S:Envelope>';

$ch = curl_init(ENDPOINT);
curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body, CURLOPT_RETURNTRANSFER => true,
  CURLOPT_TIMEOUT => 5, CURLOPT_HTTPHEADER => ['Content-Type: text/xml; charset=utf-8']]);
$xml = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);
if ($xml === false || $code !== 200) { echo '{"ok":false}'; exit; }

$doc = new DOMDocument();
if (!@$doc->loadXML($xml)) { echo '{"ok":false}'; exit; }
$get = function (DOMElement $el, string $tag) {
  $n = $el->getElementsByTagNameNS('*', $tag);
  return $n->length ? trim($n->item(0)->textContent) : null;
};
$visits = [];
foreach ($doc->getElementsByTagNameNS('*', 'MonitoredStopVisit') as $v) {
  $aimed = $get($v, 'AimedDepartureTime') ?? $get($v, 'AimedArrivalTime');
  $exp = $get($v, 'ExpectedDepartureTime') ?? $get($v, 'ExpectedArrivalTime');
  $status = strtolower($get($v, 'DepartureStatus') ?? '');
  if ($aimed && ($exp || $status === 'cancelled')) {
    $visits[] = ['aimed' => $aimed, 'expected' => $exp ?: $aimed, 'cancelled' => $status === 'cancelled'];
  }
}
$out = json_encode(['ok' => true, 'ts' => gmdate('c'), 'visits' => $visits]);
file_put_contents($cache, $out, LOCK_EX);
echo $out;
