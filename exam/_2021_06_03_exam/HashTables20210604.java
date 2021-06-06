import java.util.ArrayList;
import java.util.Arrays;
import java.util.BitSet;
import java.util.Collections;
import java.util.Deque;
import java.util.HashSet;
import java.util.LinkedList;
import java.util.List;
import java.util.Random;
import java.util.Set;
import java.util.SplittableRandom;

public class HashTables20210604 {
	private static SplittableRandom rng;
	private static Random rng2;

	private static class KHPair {
		public final String key;
		public final int hash;

		public KHPair(String key, int hash) {
			this.key = key;
			this.hash = hash;
		}

		@Override
		public int hashCode() {
			int h = this.key != null ? this.key.hashCode() * 23456789 : 0xDEADBEEF;
			h = h * 23456789 + this.hash;
			h *= 23456789;
			return h ^ h >>> 16;
		}

		@Override
		public boolean equals(Object obj) {
			if (this == obj) {
				return true;
			}
			if (obj == null || getClass() != obj.getClass()) {
				return false;
			}
			final KHPair other = (KHPair) obj;
			if (this.hash != other.hash) {
				return false;
			}
			if (this.key == null) {
				return other.key == null;
			}
			return this.key.equals(other.key);
		}

		@Override
		public String toString() {
			return this.key + ":" + this.hash;
		}
	}

	private static class SCHTable {
		@Override
		public int hashCode() {
			final int prime = 31;
			int result = 1;
			result = prime * result + this.m;
			result ^= result >>> 16;
			result = prime * result + (this.table == null ? 0 : this.table.hashCode());
			result ^= result >>> 16;
			return result;
		}

		@Override
		public boolean equals(Object obj) {
			if (this == obj) {
				return true;
			}
			if (obj == null || getClass() != obj.getClass()) {
				return false;
			}
			final SCHTable other = (SCHTable) obj;
			if (this.m != other.m) {
				return false;
			}
			if (this.table == null) {
				if (other.table != null) {
					return false;
				}
			} else if (!this.table.equals(other.table)) {
				return false;
			}
			return true;
		}

		public List<LinkedList<String>> table = new ArrayList<>();
		public final int m;
		public List<KHPair> keys;
		public boolean directionParity = false;

		public SCHTable(int modulus) {
			this.m = modulus;
			for (int i = 0; i < this.m; i++) {
				this.table.add(new LinkedList<>());
			}
			this.keys = new LinkedList<>();
		}

		public void add(int h, String key, boolean forward) {
			final int pos = h % this.m;
			this.keys.add(new KHPair(key, h));
			final Deque<String> entries = this.table.get(pos);
			if (forward) {
				entries.addFirst(key);
			} else {
				entries.addLast(key);
			}
			this.directionParity ^= forward;
		}

		// Idiocy for compatibility with buggy version.
		public void reverse(int i) {
			final int pos = i % this.m;
			if (this.table.get(pos).size() > 1) {
				Collections.reverse(this.table.get(pos));
				final KHPair firstKey = new KHPair(this.table.get(pos).getFirst(), i);
				this.keys.remove(firstKey);
				this.keys.add(firstKey);
			}
		}

		public String checkTable(int tableId) {
			final String header = "Table " + (tableId + 1) + " is ";
			if (this.directionParity) {
				return header + "valid.";
			}
			return header + "invalid -- elements can be added from the front or to the back "
					+ "of a linked list but the choice should be the same for each insertion.";
		}

	}

	private static class OAHTable {
		public KHPair[] entries;
		public final int m;
		public List<KHPair> keys;

		public OAHTable(int modulus) {
			this.m = modulus;
			this.entries = new KHPair[this.m];
			this.keys = new LinkedList<>();
		}

		public void put(int h, KHPair key) {
			final int pos = h % this.m;
			if (this.entries[pos] != null) {
				throw new AssertionError("Entry " + pos + " already occupied with " + this.entries[pos].key
						+ " when trying to insert " + key + ":" + h);
			}
			this.keys.add(key);
			this.entries[pos] = key;
		}

		public int findFirstEmptySlot() {
			for (int i = 0; i < this.m; i++) {
				if (this.entries[i] == null) {
					return i;
				}
			}
			return -1;
		}
	}

	private static String associate(String key, String value) {
		return key + "=\"" + value + "\"\n";
	}

	private static List<Integer> getRandomPermutation(int n) {
		final List<Integer> order = new LinkedList<>();

		for (var i = 0; i < n; i++) {
			order.add(i);
		}
		// FIXME: If this program ever gets used again,
		// Collections.shuffle(order, rng2) should be used!!!
		Collections.shuffle(order); // ARGH! Should of course be used with rng2!!!
		return order;
	}

	private static List<String> getRandomKeys(int k) {
		final List<String> keys = new ArrayList<>();

		// Generate keys, {'A', ..., 'A' + m -1}.
		for (int i = 0; i < k; i++) {
			final char[] c = new char[] { (char) ('A' + i) };
			keys.add(String.copyValueOf(c));
		}
		Collections.shuffle(keys, rng2);

		return keys;
	}

	private static List<SCHTable> createSeparateChainingTables(int[] hashes, int m) {
		final List<String> keys = getRandomKeys(hashes.length);

		// Add the same offset to all the hashvalues.
		final int offset = rng.nextInt(0, m * 2);
		for (int i = 0; i < hashes.length; i++) {
			hashes[i] = (hashes[i] + offset) % (m * 2) + m;
		}

		// BUG! Not deterministic but consistent with the earlier implementation.
		final List<Integer> order = getRandomPermutation(4);

		// Build the hash tables.
		final LinkedList<SCHTable> hashTables = new LinkedList<>();
		for (int i = 0; i < 4; i++) {
			final SCHTable ht = new SCHTable(m);
			final int o = order.get(i);
			final boolean firstOrder = (o & 1) == 0;
			final boolean secondOrder = (o & 2) == 0;
			for (int j = 0; j < hashes.length; j++) {
				final boolean o2 = hashes[j] % 2 == 0 ? firstOrder : secondOrder;
				ht.add(hashes[j], keys.get(j), o2);
			}
			// Idiocy to behave as a previous buggy version.
			if (offset % m == m - 1 && secondOrder ^ firstOrder) {
				ht.reverse(m - 1);
			}

			hashTables.add(ht);
		}

		return hashTables;
	}

	private static String getSeparateChainingText(List<SCHTable> tables) {
		final SCHTable keys = tables.get(0);

		// Build the key texts.
		final StringBuilder b = new StringBuilder();
		{
			int i = 0;
			for (final KHPair key : keys.keys) {
				b.append(associate("entryA_" + i, key.toString()));
				i++;
			}
		}
		for (int i = 0; i < 4; i++) {
			for (int j = 0; j < keys.m; j++) {
				final String keyString = String.join(" ", tables.get(i).table.get(j).toArray(new String[0]));
				b.append(associate("ks_" + (i + 1) + "_" + j, keyString));
			}
		}

		return b.toString();
	}

	private static List<OAHTable> createOpenAddressingTables(int[] hashes, int[][] inserted, int m) {
		final List<String> keys = getRandomKeys(hashes.length);

		final int offset = rng.nextInt(0, m);
		for (int i = 0; i < hashes.length; i++) {
			hashes[i] = (hashes[i] + offset) % (m * 2) + m;
		}

		// BUG! Not deterministic but consistent with the earlier implementation.
//		final List<Integer> order = getRandomPermutation(inserted.length);

		final List<OAHTable> hashTables = new ArrayList<>();

		for (int i = 0; i < inserted.length; i++) {
			final OAHTable ht = new OAHTable(m);
			for (int j = 0; j < inserted[i].length; j++) {
				final int hvIdx = (j + m - offset) % m;
				if (inserted[i][hvIdx] >= 0) {
					final int idx = inserted[i][hvIdx];
					ht.put(j, new KHPair(keys.get(idx), hashes[idx]));
				}
			}
			hashTables.add(ht);
		}
		return hashTables;
	}

	private static String getOpenAddressingText(final List<OAHTable> hashTables) {
		final StringBuilder b = new StringBuilder();
		final List<KHPair> keys = new ArrayList<>(hashTables.get(0).keys);
		keys.sort((x, y) -> x.hash - y.hash);

		for (int i = 0; i < keys.size(); i++) {
			b.append(associate("entryB_" + i, keys.get(i).toString()));
		}
		for (int i = 0; i < hashTables.size(); i++) {
			final OAHTable ht = hashTables.get(i);
			for (int j = 0; j < ht.m; j++) {
				b.append(associate("ko_" + (i + 1) + "_" + j, ht.entries[j] != null ? ht.entries[j].key : ""));
			}
		}
		return b.toString();
	}

	private static String getSCSolutionText(List<SCHTable> scts) {
		final Set<SCHTable> ts = new HashSet<>();
		scts.forEach(h -> ts.add(h));
		String generalSolutionText;
		if (ts.size() == 2) {
			generalSolutionText = "The intent was to have four distinct tables but in some cases there were only two.";
		} else {
			generalSolutionText = "You should have found two or three impossible tables, depending on how "
					+ "you formulate your assumption about linked lists.";
		}
		final List<SCHTable> uTables = new LinkedList<>(ts);
		final SCHTable forwardTable = new SCHTable(uTables.get(0).m);
		final SCHTable reverseTable = new SCHTable(uTables.get(0).m);
		for (final KHPair k : uTables.get(0).keys) {
			forwardTable.add(k.hash, k.key, false);
			reverseTable.add(k.hash, k.key, true);
		}
		final List<String> solutionTexts = new ArrayList<>();
		for (final SCHTable t : ts) {
			solutionTexts.add("The table with contents [" + Arrays.toString(t.table.toArray()) + "] is "
					+ (t.equals(forwardTable) || t.equals(reverseTable)
							? "possible -- elements are consistently added first or last. "
							: "impossible since elements are not consistently "
									+ "added first or last to the lists. "));
		}

		final StringBuilder b = new StringBuilder();
		b.append(associate("answerA_general", generalSolutionText));
		while (solutionTexts.size() < scts.size()) {
			solutionTexts.add("");
		}
		for (int i = 0; i < scts.size(); i++) {
			b.append(associate("answerA_" + (i + 1), solutionTexts.get(i)));
		}
		return b.toString();
	}

	private static KHPair findInOriginalPosition(OAHTable t, Set<KHPair> unused) {
		for (int i = 0; i < t.m; i++) {
			if (t.entries[i] != null) {
				final KHPair e = t.entries[i];
				if (e.hash % t.m == i && unused.contains(e)) {
					return e;
				}
			}
		}
		return null;
	}

	private static List<KHPair> getInsertionOrder(OAHTable t) {
		final Set<KHPair> unused = new HashSet<>(t.keys);
		final List<KHPair> used = new LinkedList<>();
		boolean foundOrigin;
		final BitSet seen = new BitSet();
		do {
			foundOrigin = false;
			final KHPair o = findInOriginalPosition(t, unused);
			if (o != null) {
				unused.remove(o);
				used.add(o);
				foundOrigin = true;
				seen.set(o.hash % t.m);
				for (int i = 1; i < t.m; i++) {
					final int pos = (o.hash + i) % t.m;
					final KHPair kh = t.entries[pos];
					if (kh == null) {
						break;
					}
					if (!unused.contains(kh) || !seen.get(kh.hash % t.m) && kh.hash % t.m != pos) {
						return List.of(kh, new KHPair(kh.key, pos));
					}
					used.add(kh);
					unused.remove(kh);
					seen.set((o.hash + i) % t.m);
				}
			}
		} while (foundOrigin);
		if (unused.isEmpty()) {
			return used;
		}

		// All elements not used => inconsistent table.
		for (final KHPair k : unused) {
			if (seen.get(k.hash % t.m) || k.equals(t.entries[k.hash % t.m])) {
				used.add(k);
				unused.remove(k);
				seen.set(k.hash % t.m);
			}
		}
		final List<KHPair> erronous = new LinkedList<>();
		for (final KHPair bad : unused) {
			for (int i = 0; i < t.m; i++) {
				if (t.entries[i] != null && t.entries[i].equals(bad)) {
					erronous.add(t.entries[i]);
					erronous.add(new KHPair(bad.key, i));
				}
			}
		}
		System.out.println("Erronous: " + erronous);
		return erronous;
	}

	private static String getOASolutionText(List<OAHTable> oats) {
		final StringBuffer b = new StringBuffer();
		int tIdx = 1;
		for (final OAHTable t : oats) {
			final List<KHPair> insertions = getInsertionOrder(t);
			if (insertions.size() == t.keys.size()) {
				b.append(associate("answerB_" + tIdx,
						"Table " + tIdx + " can be generated with this insertion order: " + insertions));
			} else {
				final KHPair offending = insertions.get(0);
				final int offendingPosition = insertions.get(1).hash;
				final int firstEmptyIdx = t.findFirstEmptySlot();
				b.append(associate("answerB_" + tIdx, offending + " can not be at slot " + offendingPosition
						+ " since it should end up in slot " + offending.hash % t.m + " (" + offending.hash + " % "
						+ t.m + " = " + offending.hash % t.m + "). "
						+ "The only way an element can end up in a lower numbered slot is if its original slot is occupied "
						+ "and probing has caused the index to wrap around. Since slot " + firstEmptyIdx
						+ " is empty this can't be the case; " + offending + " would have had to pass over slot "
						+ firstEmptyIdx + " to reach slot " + offendingPosition + "."));
			}
			tIdx++;
		}
		return b.toString();
	}

	public static void main(String[] args) {
		int instanceId = 0;
		boolean solution = false;
		boolean printQuestion = true;
		if (args.length > 0) {
			instanceId = args.length > 0 ? Integer.parseInt(args[0]) : 1;
			if (args.length >= 2) {
				solution = true;
				printQuestion = false;
				if (args.length == 3) {
					printQuestion = true;
				}
			}
		}

		rng = new SplittableRandom(instanceId);
		rng2 = new Random(instanceId);

		final int[] scHashes = new int[] { 3, 0, 9, 2, 6, 5, 6 };
		final List<SCHTable> scts = createSeparateChainingTables(scHashes, 5);

		final int[] oaHashes = new int[] { 1, 1, 2, 2, 3, 4, 5 };
		final int[][] oaInsertions = new int[][] { { -1, 0, 1, 3, 4, 2, 6, 5 }, { -1, 1, 2, 3, 0, 4, 5, 6 },
				{ -1, 1, 0, 4, 6, 2, 3, 5 }, { -1, 0, 1, 5, 2, 6, 3, 4 } };
		final List<OAHTable> oats = createOpenAddressingTables(oaHashes, oaInsertions, 8);
		if (printQuestion) {
			System.out.print(getSeparateChainingText(scts));
			System.out.print(getOpenAddressingText(oats));
		}
		if (solution) {
			System.out.println(getSCSolutionText(scts));
			System.out.println(getOASolutionText(oats));
		}
	}

}
