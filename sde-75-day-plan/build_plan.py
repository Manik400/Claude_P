"""Build plan.json - the one 75-day SDE plan the app, the Word doc and the Excel file all read.

    python build_plan.py [--start 2026-09-28] [--src-dir C:\\Users\\manik\\Downloads]

Backbone: 75-Day-SDE-Plan.docx (75 days, one theme a day seen from HLD, LLD in
C# and the cloud, 225 unique LeetCode problems, Saturday build / Sunday review).
From Manik_75Day_SDE_Simple_Daywise_v2.xlsx it takes the daily habits and the
simple routine. Added here: difficulty, pattern and link for every problem,
the day's DSA pattern with a one-line approach, three key points for every HLD
read, a concrete LLD deliverable, a cloud lab with the clean-up rule, the
"easy day" floor, and pass criteria for the three checkpoints.

Day 1 is a Monday, because the plan's Friday / Saturday / Sunday days are built
around the week (the source says so too). The default is the next Monday,
28 Sep 2026; the app lets you move it.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC_DIR = Path.home() / "Downloads"
DETAILED = "75-Day-SDE-Plan.docx"
SIMPLE_XLSX = "Manik_75Day_SDE_Simple_Daywise_v2.xlsx"
DEFAULT_START = "2026-09-28"

# ---------------------------------------------------------------- LeetCode difficulty (E / M / H)
DIFF = {
    "Two Sum": "E", "Contains Duplicate": "E", "Valid Anagram": "E", "Group Anagrams": "M", "Top K Frequent Elements": "M",
    "Product of Array Except Self": "M", "Valid Sudoku": "M", "Longest Consecutive Sequence": "M", "Majority Element": "E",
    "Valid Palindrome": "E", "Two Sum II - Input Array Is Sorted": "M", "3Sum": "M", "Container With Most Water": "M",
    "Remove Duplicates from Sorted Array": "E", "Move Zeroes": "E", "Trapping Rain Water": "H", "Merge Sorted Array": "E",
    "Reverse String": "E", "Best Time to Buy and Sell Stock": "E", "Longest Substring Without Repeating Characters": "M",
    "Longest Repeating Character Replacement": "M", "Permutation in String": "M", "Minimum Window Substring": "H",
    "Maximum Average Subarray I": "E", "Sliding Window Maximum": "H", "Minimum Size Subarray Sum": "M",
    "Max Consecutive Ones III": "M", "Valid Parentheses": "E", "Min Stack": "M", "Evaluate Reverse Polish Notation": "M",
    "Generate Parentheses": "M", "Daily Temperatures": "M", "Car Fleet": "M", "Next Greater Element I": "E",
    "Implement Queue using Stacks": "E", "Simplify Path": "M", "Largest Rectangle in Histogram": "H", "Online Stock Span": "M",
    "Decode String": "M", "Binary Search": "E", "Search Insert Position": "E", "Search a 2D Matrix": "M", "LRU Cache": "M",
    "Reverse Linked List": "E", "Merge Two Sorted Lists": "E", "Linked List Cycle": "E", "Reorder List": "M",
    "Remove Nth Node From End of List": "M", "Copy List with Random Pointer": "M", "Add Two Numbers": "M",
    "Find the Duplicate Number": "M", "Koko Eating Bananas": "M", "Find Minimum in Rotated Sorted Array": "M",
    "Search in Rotated Sorted Array": "M", "Time Based Key-Value Store": "M",
    "Find First and Last Position of Element in Sorted Array": "M", "Sqrt(x)": "E", "Merge k Sorted Lists": "H",
    "Intersection of Two Linked Lists": "E", "Palindrome Linked List": "E", "Middle of the Linked List": "E",
    "Remove Linked List Elements": "E", "Reverse Linked List II": "M", "Subarray Sum Equals K": "M",
    "Range Sum Query - Immutable": "E", "Find Pivot Index": "E", "Contiguous Array": "M",
    "Subarray Sums Divisible by K": "M", "Find All Anagrams in a String": "M", "Find Peak Element": "M",
    "Single Element in a Sorted Array": "M", "Capacity To Ship Packages Within D Days": "M", "Sort Colors": "M",
    "Rotate Array": "M", "Rotate Image": "M", "Invert Binary Tree": "E", "Maximum Depth of Binary Tree": "E", "Same Tree": "E",
    "Diameter of Binary Tree": "E", "Balanced Binary Tree": "E", "Subtree of Another Tree": "E", "Symmetric Tree": "E",
    "Path Sum": "E", "Binary Tree Paths": "E", "Binary Tree Level Order Traversal": "M", "Binary Tree Right Side View": "M",
    "Average of Levels in Binary Tree": "E", "Lowest Common Ancestor of a Binary Search Tree": "M",
    "Validate Binary Search Tree": "M", "Kth Smallest Element in a BST": "M",
    "Construct Binary Tree from Preorder and Inorder Traversal": "M", "Count Good Nodes in Binary Tree": "M",
    "Lowest Common Ancestor of a Binary Tree": "M", "Serialize and Deserialize Binary Tree": "H", "Delete Node in a BST": "M",
    "Convert Sorted Array to Binary Search Tree": "E", "Search in a Binary Search Tree": "E",
    "Insert into a Binary Search Tree": "M", "Range Sum of BST": "E", "Binary Tree Maximum Path Sum": "H",
    "Flatten Binary Tree to Linked List": "M", "Populating Next Right Pointers in Each Node": "M",
    "Kth Largest Element in a Stream": "E", "Last Stone Weight": "E", "Kth Largest Element in an Array": "M",
    "K Closest Points to Origin": "M", "Task Scheduler": "M", "Design Twitter": "M", "Find Median from Data Stream": "H",
    "Reorganize String": "M", "Sort Characters By Frequency": "M", "Number of Islands": "M", "Clone Graph": "M",
    "Max Area of Island": "M", "Rotting Oranges": "M", "Pacific Atlantic Water Flow": "M", "Surrounded Regions": "M",
    "Course Schedule": "M", "Course Schedule II": "M", "Find the Town Judge": "E", "Redundant Connection": "M",
    "Number of Provinces": "M", "Find if Path Exists in Graph": "E", "Word Ladder": "H", "Shortest Path in Binary Matrix": "M",
    "Open the Lock": "M", "Implement Trie (Prefix Tree)": "M", "Design Add and Search Words Data Structure": "M",
    "Longest Common Prefix": "E", "Word Search II": "H", "Word Search": "M", "Search Suggestions System": "M",
    "Merge Intervals": "M", "Insert Interval": "M", "Non-overlapping Intervals": "M",
    "Minimum Number of Arrows to Burst Balloons": "M", "Interval List Intersections": "M", "My Calendar I": "M",
    "Single Number": "E", "Number of 1 Bits": "E", "Counting Bits": "E", "Network Delay Time": "M",
    "Min Cost to Connect All Points": "M", "Cheapest Flights Within K Stops": "M", "Reverse Bits": "E", "Missing Number": "E",
    "Sum of Two Integers": "M", "Climbing Stairs": "E", "Min Cost Climbing Stairs": "E", "House Robber": "M",
    "House Robber II": "M", "Longest Palindromic Substring": "M", "Palindromic Substrings": "M", "Decode Ways": "M",
    "Coin Change": "M", "Maximum Product Subarray": "M", "Word Break": "M", "Longest Increasing Subsequence": "M",
    "Partition Equal Subset Sum": "M", "Fibonacci Number": "E", "N-th Tribonacci Number": "E", "Pascal's Triangle": "E",
    "Unique Paths": "M", "Longest Common Subsequence": "M", "Best Time to Buy and Sell Stock with Cooldown": "M",
    "Coin Change II": "M", "Target Sum": "M", "Interleaving String": "M", "Edit Distance": "M", "Minimum Path Sum": "M",
    "Maximal Square": "M", "Subsets": "M", "Combination Sum": "M", "Permutations": "M", "Subsets II": "M",
    "Combination Sum II": "M", "Palindrome Partitioning": "M", "Letter Combinations of a Phone Number": "M", "N-Queens": "H",
    "Combinations": "M", "Assign Cookies": "E", "Lemonade Change": "E", "Best Time to Buy and Sell Stock II": "M",
    "Jump Game": "M", "Jump Game II": "M", "Gas Station": "M", "Partition Labels": "M", "Hand of Straights": "M",
    "Valid Parenthesis String": "M", "Isomorphic Strings": "E", "Word Pattern": "E", "Determine if Two Strings Are Close": "M",
    "Is Graph Bipartite?": "M", "Evaluate Division": "M", "Find Eventual Safe States": "M",
    "Insert Delete GetRandom O(1)": "M", "Design HashMap": "E", "Design HashSet": "E", "First Missing Positive": "H",
    "Spiral Matrix": "M", "Set Matrix Zeroes": "M", "Palindrome Number": "E", "Roman to Integer": "E",
    "Length of Last Word": "E", "Maximum Subarray": "M", "Maximum Sum Circular Subarray": "M",
    "Longest Subarray of 1's After Deleting One Element": "M", "String to Integer (atoi)": "M", "Multiply Strings": "M",
    "Integer to Roman": "M", "Contains Duplicate II": "E", "Summary Ranges": "E", "Unique Number of Occurrences": "E",
    "Reorder Routes to Make All Paths Lead to the City Zero": "M", "Keys and Rooms": "M",
    "Nearest Exit from Entrance in Maze": "M", "Merge Strings Alternately": "E", "Greatest Common Divisor of Strings": "E",
    "Can Place Flowers": "E", "Kids With the Greatest Number of Candies": "E", "Reverse Vowels of a String": "E",
    "Reverse Words in a String": "M", "String Compression": "M", "Max Number of K-Sum Pairs": "M",
    "Increasing Triplet Subsequence": "M",
}
DIFF_NAME = {"E": "Easy", "M": "Medium", "H": "Hard"}

# ---------------------------------------------------------------- the day's DSA pattern
PATTERN_BY_DAY = {}
for days, name in [
    ((1, 2, 3), "Arrays & hashing"), ((4, 5, 6), "Two pointers"), ((7, 8, 9), "Sliding window"),
    ((10, 11, 12, 13), "Stack"), ((14, 18, 19, 24), "Binary search"), ((15, 16, 17, 20, 21), "Linked list"),
    ((22, 23), "Prefix sum"), ((25, 67), "Arrays & matrix"), (tuple(range(26, 35)), "Trees"), ((35, 36, 37), "Heap / priority queue"),
    ((38, 39, 40, 41, 42, 65, 72), "Graphs (BFS / DFS / union-find)"), ((43, 44), "Trie"), ((45, 46), "Intervals"),
    ((47, 49), "Bit manipulation"), ((48,), "Advanced graphs (Dijkstra / MST)"), (tuple(range(50, 58)), "Dynamic programming"),
    ((58, 59, 60), "Backtracking"), ((61, 62, 63), "Greedy"), ((64, 71), "Hashing"), ((66,), "Design data structures"),
    ((68, 70), "Math & strings"), ((69,), "Kadane / subarrays"), ((73, 74, 75), "Mixed interview set (LeetCode 75)"),
]:
    for d in days:
        PATTERN_BY_DAY[d] = name

PATTERN_TIPS = {
    "Arrays & hashing": "Trade memory for time: a HashMap / HashSet turns an O(n^2) scan into O(n).",
    "Two pointers": "Sorted input or a palindrome? Move two indices toward each other instead of nesting loops.",
    "Sliding window": "Grow the right edge, shrink the left while the window breaks the rule; track the best window.",
    "Stack": "Anything 'nearest greater/smaller' or matching pairs is a monotonic or plain stack.",
    "Binary search": "Search the answer space, not just arrays: find the first value where a yes/no check flips.",
    "Linked list": "Draw it. Dummy head for edits, slow/fast pointers for middle and cycles, reverse in place.",
    "Prefix sum": "sum(i..j) = prefix[j+1] - prefix[i]; a HashMap of prefix counts finds subarrays with target sums.",
    "Arrays & matrix": "In-place tricks: reverse segments, swap by index, use the first row/column as markers.",
    "Trees": "Recursion returns what the parent needs; DFS for depth/paths, BFS (queue) for levels.",
    "Heap / priority queue": "Top-K or 'always the smallest next' = heap; keep it size K for O(n log K).",
    "Graphs (BFS / DFS / union-find)": "Grid or adjacency list; BFS for shortest steps, DFS for components, topo sort for dependencies.",
    "Trie": "Each node = one character with children map + end flag; prefix queries become O(length).",
    "Intervals": "Sort by start (or end for greedy removal), then merge or compare neighbours.",
    "Bit manipulation": "x & (x-1) drops the lowest set bit; XOR cancels pairs; shifts read bits one by one.",
    "Advanced graphs (Dijkstra / MST)": "Weighted shortest path = Dijkstra with a min-heap; connect-all-cheaply = Prim/Kruskal.",
    "Dynamic programming": "Define dp[i] in words, write the recurrence, fix the base case, then optimise space.",
    "Backtracking": "Choose → explore → un-choose; prune early; sort first when duplicates must be skipped.",
    "Greedy": "Prove the local choice never hurts (exchange argument) before trusting it.",
    "Hashing": "Map each item to a canonical key (sorted string, pattern, count signature) and compare keys.",
    "Design data structures": "Combine structures: HashMap for lookup + array/list for order or random access.",
    "Math & strings": "Handle signs, overflow and edge characters first; build results digit by digit.",
    "Kadane / subarrays": "Best subarray ending here = max(x, best_ending_prev + x); keep a running global best.",
    "Mixed interview set (LeetCode 75)": "Name the pattern in the first 2 minutes, say the brute force, then optimise out loud.",
}

# ---------------------------------------------------------------- 3 key points for every HLD read
HLD_POINTS = {
    1: ["DNS resolves the name, TCP (+TLS) opens the connection, HTTP carries the request",
        "Browser cache → OS → resolver → root/TLD/authoritative servers", "Where latency is spent: DNS, handshake, server time, download"],
    2: ["Vertical = bigger machine: simple, has a ceiling and a single point of failure",
        "Horizontal = more machines: needs a load balancer and stateless app servers", "Scale reads with replicas and caches before sharding writes"],
    3: ["L4 balances TCP connections; L7 routes by path, header or cookie", "Round robin vs least connections vs IP hash, and when each wins",
        "Health checks remove bad nodes; the LB itself needs redundancy"],
    4: ["Keep session state out of app servers so any server can take any request", "Sticky sessions are a workaround with uneven load and lost sessions",
        "Session stores: Redis or a DB with a TTL; JWT moves state to the client"],
    5: ["Resources as nouns, HTTP verbs as actions, correct status codes (201, 400, 404, 409, 429)",
        "Idempotency: PUT/DELETE are, POST is not unless you add an idempotency key", "Versioning, pagination and consistent error bodies"],
    6: ["Tier 1 LB, tier 2 stateless app servers, tier 3 database", "Where each tier fails and how it recovers", "What changes at 10x traffic"],
    7: ["One page: the web request path, scaling, LB, stateless, REST", "Say each concept in two sentences without notes", "List 3 weak spots for next week"],
    8: ["SQL: schema, joins, ACID; NoSQL: flexible schema, horizontal scale", "Pick by access pattern, consistency need and scale",
        "Key-value, document, wide-column and graph stores, with one example each"],
    9: ["An index is a sorted structure (B-tree) that trades write speed for read speed", "Composite index column order matters (leftmost prefix)",
        "Read EXPLAIN plans: full scan vs index seek"],
    10: ["Primary takes writes, replicas serve reads", "Async replication means lag: read-your-own-writes issues", "Failover promotes a replica; watch for split brain"],
    11: ["Shard by a key that spreads load evenly", "Hot spots come from celebrity keys or time-ordered keys", "Cross-shard queries and rebalancing are the real cost"],
    12: ["ACID: atomicity, consistency, isolation, durability", "Isolation levels vs anomalies: dirty read, non-repeatable read, phantom",
        "When to use SERIALIZABLE and what it costs"],
    13: ["Tables: Book, Copy, Member, Loan, Reservation", "Keys, indexes and the queries they serve", "One Book has many Copies; a Loan links a Copy to a Member"],
    14: ["CAP: during a partition choose consistency or availability", "CP vs AP examples (bank ledger vs shopping cart)", "Revise databases week on one page"],
    15: ["Cache what is read often and changes rarely", "Hit ratio, latency win and staleness risk", "Layers: browser, CDN, app memory, Redis, DB buffer pool"],
    16: ["Cache-aside, write-through, write-back and when each loses data", "TTLs and eviction (LRU / LFU)", "Stampede protection: locks, jitter, early refresh"],
    17: ["CDNs serve static content from edge locations near users", "Cache keys, TTL and invalidation at the edge", "Push vs pull CDN"],
    18: ["Strong consistency: every read sees the latest write", "Eventual consistency: replicas converge later", "Cache invalidation on update: delete vs update the key"],
    19: ["Token bucket allows bursts; leaky bucket smooths output", "Fixed window vs sliding window log vs sliding window counter", "Where to enforce: gateway, service, per user or per IP"],
    20: ["Requirements: per-user limits, low latency, distributed", "Redis counters with expiry, atomic Lua scripts", "Return 429 with a Retry-After header"],
    21: ["Revise caching, CDN and consistency on one page", "Explain cache invalidation out loud", "List weak spots"],
    22: ["Queues decouple producers from consumers and absorb spikes", "Consumers scale independently; backpressure", "Ordering vs throughput trade-off"],
    23: ["Queue = one consumer gets each message; pub/sub = every subscriber gets it", "Fan-out: one event feeds many services", "Topics, subscriptions and filters"],
    24: ["At-least-once delivery means duplicates: make consumers idempotent", "Exactly-once is expensive; dedupe keys are usually enough",
         "Dead-letter queues catch poison messages; visibility timeout controls retries"],
    25: ["Channels (email, SMS, push) behind one interface", "Queue per channel, retries with backoff, user preferences", "Checkpoint: explain it in 10 minutes"],
    26: ["Serverless: no servers to manage, pay per call, scales to zero", "Cold starts, time limits and vendor lock-in", "Good for spiky, event-driven work"],
    27: ["Upload to object storage, event triggers processing", "Thumbnails generated asynchronously", "Store metadata in a DB; serve images through a CDN"],
    28: ["Revise all of Phase 1 on one page", "Re-draw 3-tier app, cache, queue and rate limiter", "Pick the 3 weakest topics"],
    29: ["API gateway: routing, auth, rate limiting, TLS in one place", "BFF: one backend per client type (web, mobile)", "Auth at the edge vs in each service"],
    30: ["Monolith first; split by business capability", "Sync (REST/gRPC) couples availability; async decouples", "Data ownership: one DB per service"],
    31: ["Service discovery: registry or DNS", "Liveness vs readiness health checks", "Containers vs VMs"],
    32: ["Authentication = who you are; authorization = what you may do", "JWT structure and why short expiry + refresh tokens",
         "OAuth2 authorization code flow"],
    33: ["Logs = events, metrics = numbers over time, traces = one request across services", "Correlation IDs tie them together", "Alert on symptoms (latency, errors), not causes"],
    34: ["Requirements: shorten, redirect, custom alias, expiry", "Key generation: base62 counter vs hash; collisions", "Read-heavy: cache hot links, 301 vs 302"],
    35: ["Revise APIs, microservices and auth", "Explain JWT and OAuth2 out loud", "List weak spots"],
    36: ["Scheduler: store jobs, pick due ones, run with retries", "Priority queues order work", "Distributed schedulers need locking so a job runs once"],
    37: ["Hash ring: adding a node moves only nearby keys", "Virtual nodes smooth out load", "Used in caches, DynamoDB, Cassandra"],
    38: ["Model relationships as nodes and edges", "Graph DBs for multi-hop queries (friends of friends)", "When a relational DB is still fine"],
    39: ["Heartbeats detect dead nodes", "Leader election: one node coordinates (Raft idea at a high level)", "Avoid split brain with quorums"],
    40: ["Bloom filter: 'definitely not' or 'maybe yes' with tiny memory", "False-positive rate vs bits and hash functions", "Uses: cache filters, username checks"],
    41: ["Entry/exit gates, spot allocation, payment", "Real-time availability per floor", "Pairs with your Parking Lot LLD"],
    42: ["Revise scheduling, hashing and coordination", "Explain consistent hashing out loud", "List weak spots"],
    43: ["Typeahead: prefix → top suggestions", "Trie with top-K cached per node, or search index", "Update ranking offline, serve from memory"],
    44: ["Offset pagination is simple but slow and unstable on big tables", "Cursor pagination uses the last seen key", "Return next-cursor tokens"],
    45: ["Optimistic locking: version check on write", "Pessimistic locking: lock first, then write", "Distributed locks with Redis and expiry"],
    46: ["Polling vs long polling vs WebSockets vs SSE", "Connection servers + a pub/sub backbone", "Presence and reconnect handling"],
    47: ["Users → requests/sec → storage/day → bandwidth", "Round numbers: 1 day ≈ 100k seconds", "Estimate peak = 2-3x average"],
    48: ["1:1 and group chat over WebSockets", "Message store, delivery and read receipts", "Fan-out on write for groups"],
    49: ["Revise search, concurrency and real-time", "Explain locking choices out loud", "List weak spots"],
    50: ["Notification v2: retries, preferences, rate limits, templates", "Priorities and quiet hours", "Checkpoint: whiteboard it in 25 minutes"],
    51: ["Estimate a real system you use (e.g. WhatsApp) end to end", "QPS, storage, bandwidth, servers", "Say assumptions out loud"],
    52: ["Pastebin: write once, read many", "Object storage for content, DB for metadata", "Expiry, access control, caching"],
    53: ["Key-value store API: get, put, delete with TTL", "Partitioning + replication + consistency level", "Hinted handoff and read repair (idea level)"],
    54: ["Revise caching strategies and CDNs", "Re-draw cache-aside with invalidation", "Map CloudFront → Front Door"],
    55: ["Web crawler: URL frontier, fetchers, parser, dedupe", "Politeness per domain, robots.txt", "Store content and follow links breadth-first"],
    56: ["Revise Phase 3 so far", "Re-draw KV store and crawler", "List weak spots"],
    57: ["Distributed rate limiting with Redis INCR / sliding window", "Atomicity with Lua scripts", "Fail open vs fail closed"],
    58: ["Job scheduler: API, store, dispatcher, workers", "Exactly-once-ish with leases and idempotent jobs", "Retries, backoff, dead letters"],
    59: ["Order service emits events; payment, inventory and shipping react", "Saga pattern for multi-step transactions", "Outbox pattern to publish reliably"],
    60: ["Dropbox: chunked upload, dedupe, sync", "Metadata DB vs block storage", "Conflict resolution across devices"],
    61: ["Revise estimation", "Two quick estimates from memory", "Check your numbers against known systems"],
    62: ["Tell your traffic platform story: data flow, queues, scale", "What you would change at 10x", "Practise the 5-minute version"],
    63: ["Revise all HLD case studies", "One template: requirements → estimate → API → data → design → scale", "List weak spots"],
    64: ["Leaderboard: Redis sorted sets", "Top-N and rank of a user", "Sharded leaderboards for huge scale"],
    65: ["Instagram: upload pipeline + feed", "Fan-out on write vs on read, celebrity problem", "Media on CDN, metadata in DB"],
    66: ["WhatsApp: persistent connections, message queue per user", "Sent / delivered / read ticks", "Offline delivery and end-to-end encryption (idea level)"],
    67: ["YouTube: upload, transcode to many resolutions, stream via CDN", "Adaptive bitrate streaming", "Metadata, views counting, recommendations (idea level)"],
    68: ["One-page HLD answer template", "Checklist: requirements, numbers, API, schema, diagram, bottlenecks", "Practise it on one random system"],
    69: ["Timed mock: Uber basic, out loud, 45 min", "Location updates, matching, trip state", "Record and review one weak moment"],
    70: ["Revise weak areas from the mocks", "Redo one mock question in 20 minutes", "List final gaps"],
    71: ["Payments: idempotency keys, retries, reconciliation", "State machine: created → authorised → captured → refunded", "Never lose or double-charge money"],
    72: ["Ticket booking: seat map, temporary holds, payment", "Locking seats with expiry", "Handling a flash sale"],
    73: ["Timed mock: URL shortener, 35 min", "Hit every section of your template", "Score yourself 1-5 per section"],
    74: ["Tell your project story in 5 minutes; record it", "Problem → design → your part → impact numbers", "Prepare 3 follow-up answers"],
    75: ["Final mock: notification system", "Final LLD mock: Parking Lot", "Write what you will keep doing after Day 75"],
}

CHECKPOINTS = {
    25: ["Solve 3 new mediums from Phase 1 patterns in 90 minutes", "Explain a 3-tier app, caching and queues in 10 minutes without notes",
         "Code a SOLID notification sender in C# with tests", "AWS Cloud Practitioner practice test: 70%+"],
    50: ["Solve 1 tree, 1 graph and 1 heap medium in 75 minutes", "Whiteboard notification system v2 in 25 minutes",
         "Implement one classic LLD (Parking Lot or Splitwise) end to end in 60 minutes", "AWS Cloud Practitioner full mock: 75%+"],
    75: ["Two timed mocks (HLD + LLD) completed and scored", "225 LeetCode problems attempted; every ↻ revisit re-solved",
         "Project story recorded in 5 minutes", "Resume bullets written for AWS and Azure projects"],
}

EASY_DAY = ["3 LeetCode (the day's easiest, or Easy re-solves)", "Walk 1 km", "Water 2.5 L", "Clean food", "HLD read only"]
HABITS = [
    {"id": "walk", "label": "Walk 1 km / 30 min exercise"},
    {"id": "water", "label": "Water 2.5–3 L (1 L by lunch, 2 L by 7 pm)", "counter": {"max": 3, "step": 0.5, "goal": 2.5, "unit": "L"}},
    {"id": "food", "label": "Healthy food, no junk"},
    {"id": "chill", "label": "1 hour to chill, guilt-free"},
    {"id": "sleep", "label": "Screens down by 11, sleep by 11:15"},
]
SCHEDULE = {
    "weekday": [
        ["7:00", "Wake, 500 ml water", "Start the water count before the phone"],
        ["7:15", "Walk 1 km+ or 30 min workout", "Outdoors if you can"],
        ["7:50", "LeetCode #1 and #2", "Fresh brain, hardest problem first; 30 min max each"],
        ["9:00", "Breakfast, get ready", "Fill a 1 L bottle for the desk"],
        ["10:00", "Office", "First litre done by lunch"],
        ["Lunch", "HLD read, 25–30 min", "The day's office topic; read or watch"],
        ["7:00 pm", "Home, shower, dinner", "Second litre done by now"],
        ["8:00 pm", "Free time", "Guilt-free, at least 1 hour"],
        ["9:00 pm", "LLD 30 min + cloud 30 min, then LeetCode #3", "Code the LLD in C#, then the cloud lab"],
        ["10:15 pm", "Wind down", "Screens down by 11"],
        ["11:15 pm", "Sleep", "Protect ~7.5 hours"],
    ],
    "saturday": [
        ["Morning", "Longer walk or workout + 3 LeetCode", "Hardest first"],
        ["Midday", "2-hour build block", "Tie the week's HLD, LLD and cloud into one small project"],
        ["Afternoon", "Clean up cloud resources", "Check the billing alarm"],
        ["Rest", "Free", ""],
    ],
    "sunday": [
        ["Morning", "Easy 1 km walk + 3 LeetCode", "Re-solve every ↻ revisit from the week first"],
        ["Midday", "45 min: revise the week on one page", "Say each topic out loud in 2 sentences"],
        ["Evening", "Meal prep for the week", "Plan Monday's first problem"],
        ["Rest", "Free", ""],
    ],
}
RULES = [
    "3 LeetCode a day: 2 in the morning, 1 at night. 30 minutes max per problem; if stuck, read the solution, mark it ↻ revisit and re-solve it on Sunday.",
    "Floor vs full: on a drained day switch to Easy day - 3 easy LeetCode + 1 km walk + water + clean food + the HLD read still counts.",
    "One theme a day: the HLD read, the LLD code and the cloud lab explain the same idea from three angles.",
    "One cloud at a time: AWS for days 1–50, Azure for 51–75, each mapped to the AWS service you already know.",
    "Cloud labs: always delete resources afterwards and keep a billing alarm on.",
    "Never double up to catch up: missed tasks go to the catch-up list and get done on Saturday or Sunday.",
    "Checkpoints on days 25, 50 and 75 have pass criteria - if one fails, repeat its weak topic before moving on.",
]
PHASES = [
    {"id": 1, "name": "Foundations", "days": [1, 25],
     "summary": "Arrays, windows, stacks, binary search, linked lists; OOP, SOLID, core patterns; scaling, databases, caching, queues; AWS core."},
    {"id": 2, "name": "Build and apply", "days": [26, 50],
     "summary": "Trees, heaps, graphs, tries, intervals; classic LLD problems; APIs, microservices, real-time; serverless, containers, deploys."},
    {"id": 3, "name": "Azure and interview mode", "days": [51, 75],
     "summary": "DP, backtracking, greedy, mixed sets; timed LLD mocks; HLD case studies; Azure mapped to AWS."},
]
TYPE_NAME = {"Office": "Office day", "Light Fri": "Light Friday", "Build Sat": "Build Saturday", "Review Sun": "Review Sunday"}


def slug(name: str) -> str:
    s = name.lower().replace("'", "").replace("(", "").replace(")", "").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def read_detailed(path: Path) -> list[list[list[str]]]:
    x = zipfile.ZipFile(path).read("word/document.xml").decode("utf8")
    rows = []
    for tr in re.findall(r"<w:tr[ >].*?</w:tr>", x, re.S):
        cells = []
        for tc in re.findall(r"<w:tc>.*?</w:tc>", tr, re.S):
            ps = [re.sub(r"<[^>]+>", "", p).replace("&apos;", "'").replace("&amp;", "&").replace("&quot;", '"')
                  for p in re.findall(r"<w:p[ >].*?</w:p>", tc, re.S)]
            cells.append([p.strip() for p in ps if p.strip()])
        rows.append(cells)
    return [r for r in rows if len(r) == 6 and r[0] and re.match(r"Day \d+$", r[0][0]) and r[5] and r[5][0].startswith("1.")]


def build(start: date, src_dir: Path) -> dict:
    rows = read_detailed(src_dir / DETAILED)
    assert len(rows) == 75, f"expected 75 day rows in {DETAILED}, found {len(rows)}"
    days = []
    for r in rows:
        n = int(r[0][0].split()[1])
        kind = r[0][1] if len(r[0]) > 1 else "Office"
        pattern = PATTERN_BY_DAY[n]
        phase = 1 if n <= 25 else 2 if n <= 50 else 3
        cloud = "AWS" if n <= 50 else "Azure"
        lc = []
        for p in r[5]:
            name = re.sub(r"^\d+\.\s*", "", p)
            d = DIFF[name]
            lc.append({"name": name, "slug": slug(name), "url": f"https://leetcode.com/problems/{slug(name)}/",
                       "difficulty": DIFF_NAME[d], "pattern": pattern})
        when = start + timedelta(days=n - 1)
        days.append({
            "day": n, "date": when.isoformat(), "weekday": when.strftime("%a"),
            "type": TYPE_NAME.get(kind, kind), "phase": phase, "week": (n - 1) // 7 + 1,
            "theme": r[1][0],
            "dsa": {"pattern": pattern, "tip": PATTERN_TIPS[pattern]},
            "leetcode": lc,
            "hld": {"topic": r[2][0], "points": HLD_POINTS[n], "when": "Lunch, 25–30 min (office topic)"},
            "lld": {"topic": r[3][0], "when": "9:00 pm, 30 min",
                    "deliverable": ("Explain it out loud in 5 minutes, then write the one-line summary" if kind == "Review Sun"
                                    else "Working C# code pushed to your practice repo, with one unit test")},
            "cloud": {"provider": cloud, "topic": r[4][0], "when": "9:30 pm, 30 min",
                      "note": "Delete what you created and check the billing alarm."},
            "checkpoint": CHECKPOINTS.get(n),
        })
    return {
        "version": 1, "title": "75-Day SDE Plan",
        "subtitle": "Modified 75 Hard for SDE interviews: DSA, HLD, LLD in C#, AWS then Azure, and daily habits",
        "start": start.isoformat(), "end": (start + timedelta(days=74)).isoformat(),
        "phases": PHASES, "rules": RULES, "schedule": SCHEDULE, "habits": HABITS, "easy_day": EASY_DAY,
        "patterns": PATTERN_TIPS, "days": days,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START, help="Day 1 (a Monday), YYYY-MM-DD")
    ap.add_argument("--src-dir", default=str(SRC_DIR))
    a = ap.parse_args()
    start = date.fromisoformat(a.start)
    if start.weekday() != 0:
        raise SystemExit(f"{start} is a {start.strftime('%A')}; Day 1 must be a Monday so the weekend days line up")
    plan = build(start, Path(a.src_dir))
    out = HERE / "plan.json"
    out.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"plan.json: {len(plan['days'])} days, {plan['start']} → {plan['end']}")


if __name__ == "__main__":
    main()
