# Public-network gas-policy deviation

The controlled local protocol and all local results remain unchanged. They use Anvil with the Shanghai target and a separately recorded 1-second block interval.

The initial Sepolia deployment used a fixed 3,000,000 gas limit carried over from the local driver. Transaction `0x7aa04173a3c037b7bf93aea8dd029fa478329dc137d023cb7a589b3293b61a05` failed with status 0 and consumed its 3,000,000 gas limit at block 11967375. A subsequent live RPC estimate for the same init code returned 10,066,523 gas. The failed receipt, diagnostic and trace request outcome are retained in `results/`.

Before retrying, the public driver was changed to estimate every new transaction on the live target network and add 20% gas headroom. Its public total gas ceiling was raised from 5,000,000 to 40,000,000, counting failed attempts, with a 16,000,000 per-transaction ceiling. A separate total quoted fee ceiling of 0.0001 SepoliaETH was added; the 3-gwei per-gas ceiling and 0.0001 reserve remain. A new transaction is refused if its full quoted gas allowance would exceed either remaining limit.

This is an adaptive public deployment demonstration. Its gas limits were revised after observing a failure, so they are not described as an unchanged preregistered public-network protocol. No cause is assigned to a particular Ethereum upgrade solely from the difference in measured gas. The local benchmark is reported independently.

Funding is a separate user-confirmed transfer from an existing Sepolia wallet. Its fees are excluded from the contract experiment totals and preserved separately in `results/sepolia_funding.json`.
