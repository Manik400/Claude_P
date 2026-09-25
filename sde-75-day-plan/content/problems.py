"""The daily problem sets: 3 LeetCode (2 Medium + 1 Hard), 1 SQL, 1 design coding question.

LEETCODE[day] = (medium, medium, hard) - the most-asked problems for the day's
DSA pattern (see build_plan.PATTERN_BY_DAY). All 225 are unique and free
(no LeetCode Premium).

SQL[day] = one LeetCode database problem, Easy or Medium, most-asked first
(the LeetCode "SQL 50" set plus the classic 17x problems). Review Sundays have
None: that day you re-solve the SQL you flagged during the week.

DESIGN[day] = one coding question on the day's HLD / LLD topic, Easy or
Medium: a LeetCode design problem when a free one fits the topic, otherwise a
short spec to implement in C# (name, difficulty, statement). Review Sundays
have None, like SQL.
"""

# (name, slug override or None) - the slug is derived from the name unless given
SLUG = {
    "All O`one Data Structure": "all-oone-data-structure",
    "Pow(x, n)": "powx-n",
}

LEETCODE = {
    1: ("Group Anagrams", "Top K Frequent Elements", "First Missing Positive"),
    2: ("Product of Array Except Self", "Longest Consecutive Sequence", "Insert Delete GetRandom O(1) - Duplicates allowed"),
    3: ("Valid Sudoku", "Majority Element II", "Count of Smaller Numbers After Self"),
    4: ("3Sum", "Container With Most Water", "Trapping Rain Water"),
    5: ("Two Sum II - Input Array Is Sorted", "4Sum", "Reverse Pairs"),
    6: ("Sort Colors", "Boats to Save People", "Maximum Score of a Good Subarray"),
    7: ("Longest Substring Without Repeating Characters", "Longest Repeating Character Replacement", "Minimum Window Substring"),
    8: ("Permutation in String", "Fruit Into Baskets", "Sliding Window Maximum"),
    9: ("Max Consecutive Ones III", "Minimum Size Subarray Sum", "Substring with Concatenation of All Words"),
    10: ("Min Stack", "Evaluate Reverse Polish Notation", "Basic Calculator"),
    11: ("Daily Temperatures", "Car Fleet", "Largest Rectangle in Histogram"),
    12: ("Decode String", "Asteroid Collision", "Longest Valid Parentheses"),
    13: ("Online Stock Span", "Remove K Digits", "Maximal Rectangle"),
    14: ("Search a 2D Matrix", "Koko Eating Bananas", "Median of Two Sorted Arrays"),
    15: ("LRU Cache", "Reorder List", "Reverse Nodes in k-Group"),
    16: ("Remove Nth Node From End of List", "Copy List with Random Pointer", "Merge k Sorted Lists"),
    17: ("Add Two Numbers", "Find the Duplicate Number", "LFU Cache"),
    18: ("Search in Rotated Sorted Array", "Find Minimum in Rotated Sorted Array", "Find Minimum in Rotated Sorted Array II"),
    19: ("Time Based Key-Value Store", "Find First and Last Position of Element in Sorted Array", "Split Array Largest Sum"),
    20: ("Rotate List", "Sort List", "Design Skiplist"),
    21: ("Reverse Linked List II", "Swap Nodes in Pairs", "All O`one Data Structure"),
    22: ("Subarray Sum Equals K", "Contiguous Array", "Shortest Subarray with Sum at Least K"),
    23: ("Subarray Sums Divisible by K", "Continuous Subarray Sum", "Number of Submatrices That Sum to Target"),
    24: ("Capacity To Ship Packages Within D Days", "Find Peak Element", "Find K-th Smallest Pair Distance"),
    25: ("Rotate Image", "Spiral Matrix", "Count of Range Sum"),
    26: ("Binary Tree Level Order Traversal", "Validate Binary Search Tree", "Binary Tree Maximum Path Sum"),
    27: ("Construct Binary Tree from Preorder and Inorder Traversal", "Lowest Common Ancestor of a Binary Tree", "Serialize and Deserialize Binary Tree"),
    28: ("Binary Tree Right Side View", "Kth Smallest Element in a BST", "Binary Tree Cameras"),
    29: ("Count Good Nodes in Binary Tree", "Path Sum II", "Vertical Order Traversal of a Binary Tree"),
    30: ("Flatten Binary Tree to Linked List", "Populating Next Right Pointers in Each Node", "Recover a Tree From Preorder Traversal"),
    31: ("Delete Node in a BST", "All Nodes Distance K in Binary Tree", "Sum of Distances in Tree"),
    32: ("Path Sum III", "Maximum Width of Binary Tree", "Maximum Sum BST in Binary Tree"),
    33: ("Binary Tree Zigzag Level Order Traversal", "Lowest Common Ancestor of a Binary Search Tree", "Kth Ancestor of a Tree Node"),
    34: ("Unique Binary Search Trees II", "Sum Root to Leaf Numbers", "Longest Path With Different Adjacent Characters"),
    35: ("Kth Largest Element in an Array", "K Closest Points to Origin", "Find Median from Data Stream"),
    36: ("Task Scheduler", "Design Twitter", "IPO"),
    37: ("Reorganize String", "Top K Frequent Words", "Sliding Window Median"),
    38: ("Number of Islands", "Clone Graph", "Word Ladder"),
    39: ("Rotting Oranges", "Pacific Atlantic Water Flow", "Shortest Path in a Grid with Obstacles Elimination"),
    40: ("Course Schedule", "Course Schedule II", "Critical Connections in a Network"),
    41: ("Redundant Connection", "Number of Provinces", "Redundant Connection II"),
    42: ("Surrounded Regions", "Open the Lock", "Bus Routes"),
    43: ("Implement Trie (Prefix Tree)", "Design Add and Search Words Data Structure", "Word Search II"),
    44: ("Search Suggestions System", "Replace Words", "Palindrome Pairs"),
    45: ("Merge Intervals", "Insert Interval", "The Skyline Problem"),
    46: ("Non-overlapping Intervals", "Minimum Number of Arrows to Burst Balloons", "Minimum Interval to Include Each Query"),
    47: ("Sum of Two Integers", "Single Number II", "Maximum XOR With an Element From Array"),
    48: ("Network Delay Time", "Cheapest Flights Within K Stops", "Swim in Rising Water"),
    49: ("Maximum XOR of Two Numbers in an Array", "Bitwise AND of Numbers Range", "Shortest Path Visiting All Nodes"),
    50: ("House Robber II", "Coin Change", "Burst Balloons"),
    51: ("Longest Palindromic Substring", "Decode Ways", "Regular Expression Matching"),
    52: ("Word Break", "Longest Increasing Subsequence", "Russian Doll Envelopes"),
    53: ("Partition Equal Subset Sum", "Maximum Product Subarray", "Distinct Subsequences"),
    54: ("Unique Paths", "Longest Common Subsequence", "Wildcard Matching"),
    55: ("Best Time to Buy and Sell Stock with Cooldown", "Coin Change II", "Best Time to Buy and Sell Stock III"),
    56: ("Target Sum", "Interleaving String", "Longest Increasing Path in a Matrix"),
    57: ("Edit Distance", "Maximal Square", "Maximum Profit in Job Scheduling"),
    58: ("Subsets", "Combination Sum", "N-Queens"),
    59: ("Permutations", "Palindrome Partitioning", "Sudoku Solver"),
    60: ("Word Search", "Letter Combinations of a Phone Number", "Word Break II"),
    61: ("Jump Game", "Gas Station", "Candy"),
    62: ("Jump Game II", "Partition Labels", "Course Schedule III"),
    63: ("Hand of Straights", "Valid Parenthesis String", "Patching Array"),
    64: ("Brick Wall", "Find All Anagrams in a String", "Longest Duplicate Substring"),
    65: ("Is Graph Bipartite?", "Evaluate Division", "Reconstruct Itinerary"),
    66: ("Insert Delete GetRandom O(1)", "Snapshot Array", "Maximum Frequency Stack"),
    67: ("Set Matrix Zeroes", "Game of Life", "Smallest Range Covering Elements from K Lists"),
    68: ("String to Integer (atoi)", "Multiply Strings", "Text Justification"),
    69: ("Maximum Subarray", "Maximum Sum Circular Subarray", "Max Sum of Rectangle No Larger Than K"),
    70: ("Integer to Roman", "Pow(x, n)", "Integer to English Words"),
    71: ("4Sum II", "Longest Palindrome by Concatenating Two Letter Words", "Substring with Largest Variance"),
    72: ("Reorder Routes to Make All Paths Lead to the City Zero", "Keys and Rooms", "Minimum Cost to Make at Least One Valid Path in a Grid"),
    73: ("Increasing Triplet Subsequence", "Max Number of K-Sum Pairs", "Sliding Puzzle"),
    74: ("String Compression", "Longest Subarray of 1's After Deleting One Element", "Minimum Cost to Hire K Workers"),
    75: ("Removing Stars From a String", "Successful Pairs of Spells and Potions", "Trapping Rain Water II"),
}

# SQL: (name, difficulty). Sundays (review) are filled in by build_plan with None.
SQL_ORDER = [
    ("Recyclable and Low Fat Products", "Easy"), ("Find Customer Referee", "Easy"), ("Big Countries", "Easy"),
    ("Combine Two Tables", "Easy"), ("Second Highest Salary", "Medium"), ("Employees Earning More Than Their Managers", "Easy"),
    ("Duplicate Emails", "Easy"), ("Customers Who Never Order", "Easy"), ("Nth Highest Salary", "Medium"),
    ("Replace Employee ID With The Unique Identifier", "Easy"), ("Rank Scores", "Medium"),
    ("Customer Who Visited but Did Not Make Any Transactions", "Easy"), ("Rising Temperature", "Easy"),
    ("Department Highest Salary", "Medium"), ("Average Time of Process per Machine", "Easy"), ("Employee Bonus", "Easy"),
    ("Consecutive Numbers", "Medium"), ("Students and Examinations", "Easy"), ("Managers with at Least 5 Direct Reports", "Medium"),
    ("Confirmation Rate", "Medium"), ("Not Boring Movies", "Easy"), ("Average Selling Price", "Easy"),
    ("Monthly Transactions I", "Medium"), ("Project Employees I", "Easy"), ("Immediate Food Delivery II", "Medium"),
    ("Percentage of Users Attended a Contest", "Easy"), ("Game Play Analysis IV", "Medium"), ("Queries Quality and Percentage", "Easy"),
    ("Number of Unique Subjects Taught by Each Teacher", "Easy"), ("Product Sales Analysis III", "Medium"),
    ("Classes With at Least 5 Students", "Easy"), ("Customers Who Bought All Products", "Medium"), ("Find Followers Count", "Easy"),
    ("Biggest Single Number", "Easy"), ("Product Price at a Given Date", "Medium"),
    ("The Number of Employees Which Report to Each Employee", "Easy"), ("Last Person to Fit in the Bus", "Medium"),
    ("Primary Department for Each Employee", "Easy"), ("Count Salary Categories", "Medium"), ("Triangle Judgement", "Easy"),
    ("Exchange Seats", "Medium"), ("Employees Whose Manager Left the Company", "Easy"), ("Movie Rating", "Medium"),
    ("Fix Names in a Table", "Easy"), ("Restaurant Growth", "Medium"), ("Patients With a Condition", "Easy"),
    ("Friend Requests II: Who Has the Most Friends", "Medium"), ("Delete Duplicate Emails", "Easy"), ("Investments in 2016", "Medium"),
    ("Group Sold Products By The Date", "Easy"), ("Market Analysis I", "Medium"), ("List the Products Ordered in a Period", "Easy"),
    ("Tree Node", "Medium"), ("Find Users With Valid E-Mails", "Easy"), ("Capital Gain/Loss", "Medium"),
    ("Game Play Analysis I", "Easy"), ("Customer Placing the Largest Number of Orders", "Easy"), ("Sales Person", "Easy"),
    ("User Activity for the Past 30 Days I", "Easy"), ("Top Travellers", "Easy"), ("Article Views I", "Easy"),
    ("Invalid Tweets", "Easy"), ("Product Sales Analysis I", "Easy"), ("Swap Sex of Employees", "Easy"),
    ("Actors and Directors Who Cooperated At Least Three Times", "Easy"),
]
SQL_SLUG = {"Capital Gain/Loss": "capital-gainloss", "Friend Requests II: Who Has the Most Friends": "friend-requests-ii-who-has-the-most-friends",
            "Find Users With Valid E-Mails": "find-users-with-valid-e-mails"}

# DESIGN[day] = ("LeetCode", name, difficulty) or ("Custom", name, difficulty, statement). None on Review Sundays.
DESIGN = {
    1: ("LeetCode", "Design Browser History", "Medium"),
    2: ("LeetCode", "Design HashMap", "Easy"),
    3: ("LeetCode", "Random Pick with Weight", "Medium"),
    4: ("LeetCode", "Design Authentication Manager", "Medium"),
    5: ("Custom", "Idempotency-key store", "Medium",
        "Implement IdempotencyStore.Execute(key, Func<Response> handler): the first call runs the handler and stores the response for 24 h; "
        "repeat calls with the same key return the stored response without running it again; a call that arrives while the first is still "
        "running waits for it (or returns 409). Keep it thread-safe."),
    6: ("Custom", "Three-tier Todo API in one process", "Easy",
        "Build TodoController -> TodoService -> ITodoRepository (in-memory) for create/get/list/complete. Validation lives in the service, "
        "storage behind the interface, so swapping the repository for a DB class changes no other layer. Add one unit test per layer."),
    8: ("LeetCode", "Design HashSet", "Easy"),
    9: ("LeetCode", "Design a Number Container System", "Medium"),
    10: ("LeetCode", "Snapshot Array", "Medium"),
    11: ("Custom", "Shard router", "Medium",
         "Implement ShardRouter with Route(key) = hash(key) mod N. Then write MovedKeys(keys, oldN, newN) and show how many of 10,000 keys "
         "move when N goes from 4 to 5 - the number you quote when explaining why consistent hashing exists."),
    12: ("LeetCode", "Design an ATM Machine", "Medium"),
    13: ("LeetCode", "Seat Reservation Manager", "Medium"),
    15: ("LeetCode", "LRU Cache", "Medium"),
    16: ("LeetCode", "Time Based Key-Value Store", "Medium"),
    17: ("Custom", "Edge cache with TTL and prefix purge", "Easy",
         "Implement EdgeCache: Get(path), Put(path, body, ttlSeconds) and Purge(prefix) that drops every path starting with the prefix "
         "(e.g. /images/). Expired entries are never returned. Use a clock you can fake in tests."),
    18: ("LeetCode", "Stock Price Fluctuation", "Medium"),
    19: ("LeetCode", "Number of Recent Calls", "Easy"),
    20: ("LeetCode", "Tweet Counts Per Frequency", "Medium"),
    22: ("LeetCode", "Design Circular Queue", "Medium"),
    23: ("LeetCode", "Design Twitter", "Medium"),
    24: ("Custom", "Idempotent message consumer", "Medium",
         "Implement Consumer.Handle(Message m) for at-least-once delivery: skip messages whose Id was processed in the last 10 minutes, "
         "retry a failing handler up to 3 times with backoff, then move the message to a dead-letter list."),
    25: ("Custom", "Notification throttler", "Medium",
         "Implement Throttler.Allow(userId, channel) so each user gets at most 3 push, 5 email and 10 in-app notifications per hour, "
         "with quiet hours 23:00-07:00 for push. Return the reason when a notification is held back."),
    26: ("LeetCode", "Design an Ordered Stream", "Easy"),
    27: ("LeetCode", "Design Circular Deque", "Medium"),
    29: ("Custom", "API gateway route matcher", "Medium",
         "Implement Router.Add(pattern, service) with patterns like /users/{id}/orders and Router.Match(path) returning the service and "
         "path parameters. The most specific route wins; unknown paths return null. Aim for lookups faster than scanning every route."),
    30: ("LeetCode", "Design Underground System", "Medium"),
    31: ("Custom", "Service registry with heartbeats", "Easy",
         "Implement Registry.Register(service, instance), Heartbeat(instance, t) and Healthy(service, t) that returns only instances "
         "that sent a heartbeat in the last 15 seconds, round-robin ordered."),
    32: ("Custom", "Signed token with expiry", "Medium",
         "Implement TokenService.Issue(userId, roles, ttl) returning base64url(payload).base64url(HMACSHA256 signature) and Validate(token) "
         "that rejects bad signatures and expired tokens. This is the idea behind a JWT - explain what it does not protect."),
    33: ("Custom", "Rolling latency percentiles", "Medium",
         "Implement Metrics.Record(endpoint, ms, t) and P50/P99(endpoint, t) over the last 60 seconds. Keep memory bounded "
         "(bucket per second) and explain the accuracy you gave up."),
    34: ("LeetCode", "Encode and Decode TinyURL", "Medium"),
    36: ("LeetCode", "Single-Threaded CPU", "Medium"),
    37: ("Custom", "Consistent hash ring", "Medium",
         "Implement HashRing with AddNode(node, virtualNodes), RemoveNode(node) and GetNode(key) using a sorted map of hashes. "
         "Measure how many of 10,000 keys move when a 5th node joins 4 (compare with the shard router from day 11)."),
    38: ("LeetCode", "Operations on Tree", "Medium"),
    39: ("Custom", "Lease-based leader election", "Medium",
         "Simulate 3 nodes that try to acquire a lease (key, owner, expiresAt) with compare-and-set on a shared store. The leader renews "
         "every 2 s; if it stops, another node takes over after the lease expires. Show no two leaders overlap."),
    40: ("Custom", "Bloom filter", "Easy",
         "Implement BloomFilter(bits, hashCount) with Add(item) and MightContain(item) using double hashing. Insert 10,000 items and "
         "measure the false-positive rate for 1% and 5% targets against the formula."),
    41: ("LeetCode", "Design Parking System", "Easy"),
    43: ("LeetCode", "Map Sum Pairs", "Medium"),
    44: ("LeetCode", "Binary Search Tree Iterator", "Medium"),
    45: ("Custom", "Seat hold with optimistic locking", "Medium",
         "Implement SeatService.Hold(showId, seatId, userId) with a version number per seat: a hold succeeds only if the version it read is "
         "still current, holds expire after 5 minutes, Confirm(holdId) turns a hold into a booking. Run 100 parallel holds on one seat."),
    46: ("Custom", "In-memory chat room broadcaster", "Medium",
         "Implement ChatHub.Join(room, user, Action<Message> deliver), Leave and Send(room, from, text) that delivers to everyone else in "
         "order, keeps the last 50 messages for late joiners, and never blocks the sender on a slow receiver (per-user queue)."),
    47: ("Custom", "Capacity estimator", "Easy",
         "Write Estimate(dailyActiveUsers, requestsPerUserPerDay, bytesPerRequest, peakFactor) returning average QPS, peak QPS, storage per "
         "day and per year, and servers needed at 1,000 QPS each. Check it against WhatsApp-scale numbers."),
    48: ("Custom", "Group chat with read receipts", "Medium",
         "Extend the day-46 hub: Send returns a messageId; MarkRead(user, messageId) records reads; Receipts(messageId) returns who has "
         "read it. Store receipts compactly (last-read pointer per user) rather than per message."),
    50: ("Custom", "Retry scheduler with backoff and DLQ", "Medium",
         "Implement RetryScheduler.Submit(job) that runs jobs, retries failures at 1 s, 2 s, 4 s, 8 s with jitter, and moves a job to a "
         "dead-letter list after 4 failures. Jobs carry an idempotency key so a retry never double-sends."),
    51: ("LeetCode", "Apply Discount Every n Orders", "Medium"),
    52: ("Custom", "Paste store with expiry", "Easy",
         "Implement PasteStore.Create(text, ttl) returning a 7-character base62 id, Get(id) that returns null after expiry, and a "
         "background sweep. Ids must not collide; explain the collision math for 10 million pastes."),
    53: ("Custom", "KV store with TTL and snapshots", "Medium",
         "Implement Kv.Put(key, value, ttl), Get(key), Delete(key), Snapshot() returning an id, and GetAt(key, snapshotId). "
         "Snapshots must be O(1) to take (copy-on-write or versioned values)."),
    54: ("LeetCode", "Design Memory Allocator", "Medium"),
    55: ("Custom", "Polite crawler frontier", "Medium",
         "Implement Frontier.Add(url) and Next(now) returning the next URL to fetch: breadth-first, each URL once (normalise it), and at most "
         "one request per domain every 2 seconds. Next returns null when every domain is cooling down."),
    57: ("Custom", "Sliding-window-counter rate limiter", "Medium",
         "Implement RateLimiter.Allow(clientId, now) with the sliding window counter: current-minute count + previous-minute count x "
         "overlap. 100 requests per minute. Compare its error with a fixed window on a burst at the minute boundary."),
    58: ("LeetCode", "Smallest Number in Infinite Set", "Medium"),
    59: ("Custom", "Order state machine", "Medium",
         "Implement Order with states Created -> Paid -> Packed -> Shipped -> Delivered, plus Cancelled (only before Shipped) and Refunded "
         "(only after Paid). Invalid transitions throw. Every transition emits an event; replaying the events rebuilds the order."),
    60: ("Custom", "In-memory file system", "Medium",
         "Implement FileSystem.Mkdir(path), Ls(path) (sorted names, or the file name for a file), AddContent(filePath, text) that appends, "
         "and ReadContent(filePath). Paths look like /a/b/c. Use the Composite idea: directories and files share a node type."),
    61: ("Custom", "Error-rate alert", "Easy",
         "Implement Alerting.Record(ok, t) and ShouldAlert(t): alert when more than 5% of requests in the last 5 minutes failed and there "
         "were at least 100 requests, and do not alert again for 10 minutes after firing."),
    62: ("LeetCode", "Frequency Tracker", "Medium"),
    64: ("Custom", "Leaderboard", "Medium",
         "Implement Leaderboard.AddScore(playerId, score) (adds to the total), Top(k) returning the sum of the top k scores, Rank(playerId) "
         "and Reset(playerId). Target O(log n) per update with a sorted structure."),
    65: ("Custom", "Merged news feed", "Medium",
         "Given each followee's posts newest-first, implement Feed(userId, cursor, pageSize) that merges them newest-first with a heap and "
         "returns the next cursor, so page 2 continues exactly where page 1 stopped even if new posts arrive."),
    66: ("Custom", "Message delivery states", "Medium",
         "Implement Delivery.Sent(msgId, recipients), Delivered(msgId, user), Read(msgId, user) and Status(msgId) returning single tick, "
         "double tick or blue ticks (all recipients read). Out-of-order events (Read before Delivered) must still end in the right state."),
    67: ("Custom", "Deduplicated view counter", "Medium",
         "Implement Views.Record(videoId, userId, t) that counts a view at most once per user per video every 30 seconds, and Count(videoId). "
         "Then batch counts per minute before writing them, to show how YouTube-style counters avoid a DB write per view."),
    68: ("LeetCode", "Design Front Middle Back Queue", "Medium"),
    69: ("Custom", "Nearest drivers", "Medium",
         "Implement Drivers.Update(driverId, lat, lng) and Nearest(lat, lng, k) using grid cells (like geohash buckets): look in the rider's "
         "cell, then the ring around it, until k drivers are found. Compare with scanning every driver."),
    71: ("LeetCode", "Simple Bank System", "Medium"),
    72: ("LeetCode", "My Calendar I", "Medium"),
    73: ("Custom", "Short-code generator", "Easy",
         "Implement Base62.Encode(long id) and Decode(string code), then IdGenerator.Next() that never repeats across 3 app servers "
         "(each owns a range, refilled in blocks of 1,000). This is the core of the URL shortener mock."),
    74: ("LeetCode", "Design a Food Rating System", "Medium"),
    75: ("LeetCode", "My Calendar II", "Medium"),
}
