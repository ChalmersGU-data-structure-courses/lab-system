import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;
import java.util.SplittableRandom;

public class HashTables20210603 {
        private static SplittableRandom rng;
        private static Random rng2;

	private static String associate(String key, String value) {
		return key + "=\"" + value + "\"\n";
	}

	private static String getKeys(String prefix, List<String> keys, int base, boolean forward) {
		int p = 0;
		String[] ks = new String[keys.size()];
		for(int i = forward ? 0 : keys.size() - 1;
		    forward ? i < keys.size() : i >= 0;
		        i = (forward ? i + 1 : i - 1)) {
			String key;
			if(i < keys.size()) {
			    key = keys.get(i);
			    ks[p] = keys.get(i);
			}
			p++;
		}
		return associate(prefix + base, String.join(" ", ks));
	}

	private static String getSeparateChainingText(int[] hashes, int m) {
		List<String> keys = new ArrayList<>();
		for(int i = 0; i < hashes.length; i++) {
			char[] c = new char[] { (char) ('A' + i)};
			keys.add(String.copyValueOf(c));
		}
		Collections.shuffle(keys, rng2);
		int offset = rng.nextInt(0, m * 2);
		for(int i = 0; i < hashes.length; i++) {
			hashes[i] = (hashes[i] + offset) % (m * 2) + m;
		}
		StringBuilder b = new StringBuilder();
		for(int i = 0; i < hashes.length; i++) {
			b.append(associate("entryA_" + i, keys.get(i) + ":" + Integer.toString(hashes[i])));
		}

		List<Integer> order = new ArrayList<>();
		for(int i = 0; i < 4; i++) {
			order.add(i);
		}
		Collections.shuffle(order);

		for(int i = 0; i < 4; i++) {
			List<List<String>> hashTable = new ArrayList<>();
			for(int j = 0; j < m; j++) {
				hashTable.add(new ArrayList<>());
			}
			for(int j = 0; j < hashes.length; j++) {
			        hashTable.get(hashes[j] % m).add(keys.get(j));
			}
			int o = order.get(i);
			boolean firstOrder = (o & 1) == 0;
			boolean secondOrder = (o & 2) == 0;
			for(int j = 0; j < m; j++) {
				boolean o2 = j % 2 == 0 ? firstOrder : secondOrder;
				b.append(getKeys("ks_" + (i + 1) + "_", hashTable.get(j), j, o2));
			}
		}

		return b.toString();
	}

	private static String printOpenAddressing(int[] hashes, int[][] inserted, int m) {
		List<String> keys = new ArrayList<>();
		for(int i = 0; i < hashes.length; i++) {
			char[] c = new char[] { (char) ('A' + i)};
			keys.add(String.copyValueOf(c));
		}
		Collections.shuffle(keys, rng2);
		int offset = rng.nextInt(0, m * 2);
		for(int i = 0; i < hashes.length; i++) {
			hashes[i] = (hashes[i] + offset) % (m * 2) + m * 2;
		}
		StringBuilder b = new StringBuilder();
		List<Integer> order = new ArrayList<>();
		for(int i = 0; i < 4; i++) {
			order.add(i);
		}
		Collections.shuffle(order);
		for(int i = 0; i < hashes.length; i++) {
			b.append(associate("entryB_" + i, keys.get(i) + ":" + Integer.toString(hashes[i])));
		}

		for(int i = 0; i < inserted.length; i++) {
			for(int j = 0; j < inserted[i].length; j++) {
				b.append(associate("ko_" + (i + 1) + "_" + j,
						   inserted[i][(j + offset) % m] >= 0 ? keys.get(inserted[i][(j + offset) % m]) : ""));
			}
		}
		return b.toString();
	}

	public static void main(String[] args) {
		int instanceId = args.length > 0 ? Integer.parseInt(args[0]) : 1;
		rng = new SplittableRandom(instanceId);
		rng2 = new Random(instanceId);

		String scInstance = getSeparateChainingText(new int[] {3, 0, 9, 2, 6, 5, 6}, 5);
		String oaInstance = printOpenAddressing(new int[] {1, 1, 2, 2, 3, 4, 5},
							new int[][] {
							    {-1, 0, 1, 3, 4, 2, 6, 5},
							    {-1, 1, 2, 3, 0, 4, 5, 6},
							    {-1, 1, 0, 4, 6, 2, 3, 5},
							    {-1, 0, 1, 5, 2, 6, 3, 4}
							}, 8);
		System.out.print(scInstance);
		System.out.print(oaInstance);
	}
}
