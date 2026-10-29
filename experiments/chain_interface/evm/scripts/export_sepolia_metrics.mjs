// Read-only receipt and block audit for the four successful paper operations.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {formatUnits} from 'ethers';
import {ROOT, readJSON, writeJSON, providerFor} from './common.mjs';

const config = readJSON('config/sepolia.json');
const state = readJSON('results/sepolia_deployment.json');
const provider = providerFor(config.rpcUrl, config.chainId);
const operations = {
  deployment: 'Deployment',
  anchor_B_stage_group: 'Stage-inclusive record',
  anchor_A_no_stage: 'Stage-excluded record',
  metadata_revision_check: 'Metadata revision',
};
const selected = state.transactions.filter(t => t.status === 1 && t.label in operations);
assert.equal(selected.length, 4);
assert.equal(new Set(selected.map(t => t.label)).size, 4);
const raw = {retrievedAtUTC: new Date().toISOString(), rpcUrl: config.rpcUrl, transactions: []};
const auditChecks = [];
const check = (condition, name) => {assert.ok(condition, name); auditChecks.push(name);};
const localISO = iso => new Date(Date.parse(iso) + 8 * 3600 * 1000).toISOString().replace('Z', '+08:00');

try {
  const chainId = Number(BigInt(await provider.send('eth_chainId', [])));
  check(chainId === 11155111 && chainId === state.chainId, 'Sepolia chain ID');
  const rows = [];
  for (const [index, logged] of selected.entries()) {
    const [receipt, transaction] = await Promise.all([
      provider.send('eth_getTransactionReceipt', [logged.txHash]),
      provider.send('eth_getTransactionByHash', [logged.txHash]),
    ]);
    assert.ok(receipt && transaction, logged.txHash);
    const block = await provider.send('eth_getBlockByNumber', [receipt.blockNumber, false]);
    assert.ok(block, 'Block available');
    const gasUsed = BigInt(receipt.gasUsed);
    const gasPrice = BigInt(receipt.effectiveGasPrice);
    const fee = gasUsed * gasPrice;
    check(receipt.transactionHash === logged.txHash && transaction.hash === logged.txHash, `${logged.label}: transaction hash`);
    check(Number(BigInt(receipt.status)) === 1, `${logged.label}: successful receipt`);
    check(Number(BigInt(receipt.blockNumber)) === logged.blockNumber, `${logged.label}: logged block number`);
    check(block.hash === receipt.blockHash && transaction.blockHash === block.hash, `${logged.label}: canonical block hash`);
    check(block.transactions.includes(logged.txHash), `${logged.label}: transaction present in block`);
    check(gasUsed === BigInt(logged.gasUsed), `${logged.label}: gas used`);
    check(gasPrice === BigInt(logged.gasPriceWei), `${logged.label}: effective gas price`);
    check(fee === BigInt(logged.feeWei), `${logged.label}: exact fee`);
    check(transaction.from.toLowerCase() === state.deployer.toLowerCase(), `${logged.label}: dedicated sender`);
    check(logged.label === 'deployment'
      ? receipt.contractAddress.toLowerCase() === state.contractAddress.toLowerCase()
      : transaction.to.toLowerCase() === state.contractAddress.toLowerCase(), `${logged.label}: target contract`);
    check(Number.isFinite(logged.receiptLatencyMilliseconds) && logged.receiptLatencyMilliseconds > 0,
      `${logged.label}: original monotonic client latency present`);
    const blockTimestampUnixSeconds = Number(BigInt(block.timestamp));
    const blockTimeUTC = new Date(blockTimestampUnixSeconds * 1000).toISOString();
    rows.push({
      id: `T${index + 1}`, label: logged.label, operation: operations[logged.label],
      txHash: logged.txHash, explorerURL: logged.explorerURL, status: 1,
      nonce: Number(BigInt(transaction.nonce)),
      blockNumber: logged.blockNumber, blockHash: block.hash,
      gasLimit: BigInt(transaction.gas).toString(), gasUsed: gasUsed.toString(),
      effectiveGasPriceWei: gasPrice.toString(), effectiveGasPriceGwei: formatUnits(gasPrice, 9),
      feeWei: fee.toString(), feeSepoliaETH: formatUnits(fee, 18),
      feeNanoSepoliaETH: formatUnits(fee, 9),
      submissionStartedUTC: logged.startedUTC, submissionStartedUTC8: localISO(logged.startedUTC),
      submissionMilliseconds: logged.submissionMilliseconds,
      blockTimestampUnixSeconds, blockTimeUTC, blockTimeUTC8: localISO(blockTimeUTC),
      receiptObservedUTC: logged.receiptObservedUTC, receiptObservedUTC8: localISO(logged.receiptObservedUTC),
      receiptLatencyMilliseconds: logged.receiptLatencyMilliseconds,
      confirmationsRequested: logged.confirmationsRequested,
    });
    raw.transactions.push({label: logged.label, transaction, receipt, block});
  }
  const gasTotal = rows.reduce((a, t) => a + BigInt(t.gasUsed), 0n);
  const feeTotal = rows.reduce((a, t) => a + BigInt(t.feeWei), 0n);
  const result = {
    schema: 'registry-sepolia-paper-metrics/v1', retrievedAtUTC: raw.retrievedAtUTC,
    chainId, contractAddress: state.contractAddress,
    selection: 'One successful transaction per operation: deployment, two B1 registrations and one metadata revision.',
    timingDefinitions: {
      submissionStartedUTC: 'Original client wall-clock timestamp at submission start, before the RPC send completes.',
      blockTimeUTC: 'Canonical inclusion-block timestamp returned by eth_getBlockByNumber; seconds resolution.',
      receiptObservedUTC: 'Original client wall-clock timestamp when the one-confirmation receipt was observed.',
      receiptLatencyMilliseconds: 'Original monotonic elapsed time from submission start to receipt observation; not consensus finality.',
      UTC8: 'UTC+08:00, Asia/Shanghai; the manuscript table uses UTC.',
    },
    feeDefinition: 'feeWei = gasUsed * effectiveGasPriceWei; 1 SepoliaETH = 10^18 wei.',
    transactions: rows,
    totals: {successfulTransactions: rows.length, gasUsed: gasTotal.toString(), feeWei: feeTotal.toString(),
      feeSepoliaETH: formatUnits(feeTotal, 18), feeNanoSepoliaETH: formatUnits(feeTotal, 9)},
    audit: {allPassed: true, checks: auditChecks},
  };
  writeJSON('results/sepolia_transaction_metrics.json', result);
  writeJSON('results/sepolia_metrics_rpc_snapshot.json', raw);
  const columns = Object.keys(rows[0]);
  const csvCell = v => '"' + String(v).replaceAll('"', '""') + '"';
  fs.writeFileSync(path.join(ROOT, 'results/sepolia_transaction_metrics.csv'),
    columns.join(',') + '\n' + rows.map(row => columns.map(k => csvCell(row[k])).join(',')).join('\n') + '\n');
  console.log(JSON.stringify({allPassed: true, checks: auditChecks.length, totals: result.totals,
    rows: rows.map(t => ({operation: t.operation, blockTimeUTC: t.blockTimeUTC, feeSepoliaETH: t.feeSepoliaETH}))}, null, 2));
} finally {
  provider.destroy();
}
