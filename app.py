#!/usr/bin/env python3
"""
NHL Semantic Analytics - Interactive Web Interface
Streamlit app for exploring Oracle 26ai vector search capabilities
"""

import streamlit as st
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from exploration.hybrid_search import HybridSearchEngine
import pandas as pd
from datetime import datetime, timedelta

# Page configuration
st.set_page_config(
    page_title="NHL Semantic Analytics",
    page_icon="🏒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        text-align: center;
        margin-bottom: 2rem;
    }
    .result-card {
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
        background-color: #f0f2f6;
        margin-bottom: 1rem;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'search_engine' not in st.session_state:
    st.session_state.search_engine = HybridSearchEngine()
    st.session_state.search_engine.connect()

# Header
st.markdown('<div class="main-header">🏒 NHL Semantic Analytics</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Oracle 26ai Vector Search Platform • BU 779 Advanced Database Management</div>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("⚙️ Search Settings")

    search_type = st.radio(
        "Search Type",
        ["🏟️ Games", "👤 Players", "🔍 Similar Players"],
        help="Choose what you want to search for"
    )

    st.markdown("---")

    if search_type == "🏟️ Games":
        st.subheader("Game Filters")

        # Team filter
        teams = st.multiselect(
            "Teams",
            ["Boston Bruins", "Colorado Avalanche", "Tampa Bay Lightning",
             "Toronto Maple Leafs", "Pittsburgh Penguins", "Washington Capitals",
             "New York Rangers", "Carolina Hurricanes", "Vegas Golden Knights",
             "Edmonton Oilers", "Calgary Flames", "Dallas Stars", "Minnesota Wild"],
            help="Filter by specific teams"
        )

        # Goal filters
        col1, col2 = st.columns(2)
        with col1:
            min_goals = st.number_input("Min Total Goals", min_value=0, max_value=20, value=0, step=1)
        with col2:
            max_goals = st.number_input("Max Total Goals", min_value=0, max_value=20, value=20, step=1)

        # Goal differential
        min_diff = st.slider("Min Goal Differential", min_value=0, max_value=10, value=0, step=1)

        # Date range
        date_col1, date_col2 = st.columns(2)
        with date_col1:
            date_from = st.date_input("From Date", value=datetime(2020, 1, 1))
        with date_col2:
            date_to = st.date_input("To Date", value=datetime(2026, 12, 31))

        # Overtime
        overtime_only = st.checkbox("Overtime/Shootout Only")

        # Results count
        top_k = st.slider("Number of Results", min_value=5, max_value=50, value=10, step=5)

    elif search_type == "👤 Players":
        st.subheader("Player Filters")

        # Position filter
        positions = st.multiselect(
            "Positions",
            ["C", "L", "R", "D", "G"],
            help="Center, Left Wing, Right Wing, Defense, Goalie"
        )

        # Points filter
        col1, col2 = st.columns(2)
        with col1:
            min_points = st.number_input("Min Points", min_value=0, max_value=100, value=0, step=5)
        with col2:
            max_points = st.number_input("Max Points", min_value=0, max_value=150, value=150, step=5)

        # Games played
        min_games = st.number_input("Min Games Played", min_value=0, max_value=82, value=0, step=10)

        # Season filter
        seasons = st.multiselect(
            "Seasons",
            [20202021, 20212022, 20222023, 20232024, 20242025, 20252026],
            help="Filter by specific seasons"
        )

        # Results count
        top_k = st.slider("Number of Results", min_value=5, max_value=50, value=10, step=5)

    else:  # Similar Players
        st.subheader("Similarity Settings")

        reference_player = st.text_input(
            "Reference Player",
            value="McDavid",
            help="Enter player name to find similar players"
        )

        same_position = st.checkbox("Same Position Only", value=True)
        top_k = st.slider("Number of Results", min_value=5, max_value=20, value=10, step=1)

# Main content
if search_type == "🏟️ Games":
    st.header("🏟️ Game Search")

    # Example queries
    st.subheader("💡 Try these queries:")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Blowout Victories"):
            st.session_state.query = "dominant one-sided blowout crushing victory"
    with col2:
        if st.button("Offensive Shootouts"):
            st.session_state.query = "offensive high scoring many goals shootout"
    with col3:
        if st.button("Overtime Thrillers"):
            st.session_state.query = "dramatic thriller overtime close nail-biter"

    # Search query
    query = st.text_input(
        "Search Query",
        value=st.session_state.get('query', ''),
        placeholder="Enter your search query (e.g., 'dramatic comeback overtime thriller')",
        help="Describe the type of game you're looking for in natural language"
    )

    if st.button("🔍 Search", type="primary"):
        if query:
            with st.spinner("Searching..."):
                results = st.session_state.search_engine.search_games(
                    query=query,
                    teams=teams if teams else None,
                    min_total_goals=min_goals if min_goals > 0 else None,
                    max_total_goals=max_goals if max_goals < 20 else None,
                    min_goal_diff=min_diff if min_diff > 0 else None,
                    date_from=date_from.strftime("%Y-%m-%d"),
                    date_to=date_to.strftime("%Y-%m-%d"),
                    overtime_only=overtime_only,
                    top_k=top_k
                )

                if results:
                    # Summary metrics
                    st.subheader(f"📊 Found {len(results)} Games")

                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        avg_goals = sum(r['home_score'] + r['away_score'] for r in results) / len(results)
                        st.metric("Avg Total Goals", f"{avg_goals:.1f}")
                    with col2:
                        avg_diff = sum(abs(r['home_score'] - r['away_score']) for r in results) / len(results)
                        st.metric("Avg Goal Diff", f"{avg_diff:.1f}")
                    with col3:
                        ot_games = sum(1 for r in results if r['period_type'] in ['OT', 'SO'])
                        st.metric("OT/SO Games", ot_games)
                    with col4:
                        avg_sim = sum(r['similarity'] for r in results) / len(results)
                        st.metric("Avg Similarity", f"{avg_sim:.3f}")

                    # Results
                    st.subheader("🎯 Results")
                    for i, game in enumerate(results, 1):
                        total = game['home_score'] + game['away_score']
                        diff = abs(game['home_score'] - game['away_score'])
                        winner = game['home_team'] if game['home_score'] > game['away_score'] else game['away_team']

                        with st.expander(
                            f"#{i} • {game['away_team']} @ {game['home_team']} • "
                            f"{game['away_score']}-{game['home_score']} • "
                            f"Similarity: {game['similarity']:.3f}"
                        ):
                            col1, col2 = st.columns([1, 2])

                            with col1:
                                st.markdown(f"**Date:** {game['game_date'].strftime('%B %d, %Y')}")
                                st.markdown(f"**Winner:** {winner}")
                                st.markdown(f"**Total Goals:** {total}")
                                st.markdown(f"**Goal Diff:** {diff}")
                                if game['period_type'] != 'REG':
                                    st.markdown(f"**Period:** {game['period_type']}")
                                st.markdown(f"**Similarity:** {game['similarity']:.4f}")

                            with col2:
                                st.markdown("**Narrative:**")
                                st.info(game['narrative'])
                else:
                    st.warning("No results found. Try adjusting your filters or query.")
        else:
            st.warning("Please enter a search query")

elif search_type == "👤 Players":
    st.header("👤 Player Search")

    # Example queries
    st.subheader("💡 Try these queries:")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Elite Scorers"):
            st.session_state.player_query = "elite scorer offensive force superstar"
    with col2:
        if st.button("Playmakers"):
            st.session_state.player_query = "playmaker assists distributor vision passer"
    with col3:
        if st.button("Physical Players"):
            st.session_state.player_query = "physical tough gritty enforcer hits"

    # Search query
    query = st.text_input(
        "Search Query",
        value=st.session_state.get('player_query', ''),
        placeholder="Enter your search query (e.g., 'elite playmaker strong assists')",
        help="Describe the type of player you're looking for"
    )

    if st.button("🔍 Search", type="primary"):
        if query:
            with st.spinner("Searching..."):
                results = st.session_state.search_engine.search_players(
                    query=query,
                    positions=positions if positions else None,
                    min_points=min_points if min_points > 0 else None,
                    max_points=max_points if max_points < 150 else None,
                    min_games=min_games if min_games > 0 else None,
                    seasons=seasons if seasons else None,
                    top_k=top_k
                )

                if results:
                    # Summary metrics
                    st.subheader(f"📊 Found {len(results)} Player-Seasons")

                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        avg_pts = sum(r['points'] for r in results) / len(results)
                        st.metric("Avg Points", f"{avg_pts:.1f}")
                    with col2:
                        avg_goals = sum(r['goals'] for r in results) / len(results)
                        st.metric("Avg Goals", f"{avg_goals:.1f}")
                    with col3:
                        avg_assists = sum(r['assists'] for r in results) / len(results)
                        st.metric("Avg Assists", f"{avg_assists:.1f}")
                    with col4:
                        avg_sim = sum(r['similarity'] for r in results) / len(results)
                        st.metric("Avg Similarity", f"{avg_sim:.3f}")

                    # Results
                    st.subheader("🎯 Results")
                    for i, player in enumerate(results, 1):
                        with st.expander(
                            f"#{i} • {player['name']} ({player['position']}) • "
                            f"{player['season']} • {player['points']} pts • "
                            f"Similarity: {player['similarity']:.3f}"
                        ):
                            col1, col2 = st.columns([1, 2])

                            with col1:
                                st.markdown(f"**Season:** {player['season']}")
                                st.markdown(f"**Position:** {player['position']}")
                                st.markdown(f"**Games:** {player['games_played']}")
                                st.markdown(f"**Points:** {player['points']} ({player['goals']}G {player['assists']}A)")
                                st.markdown(f"**+/-:** {player['plus_minus']:+d}")
                                st.markdown(f"**Similarity:** {player['similarity']:.4f}")

                            with col2:
                                st.markdown("**Narrative:**")
                                st.info(player['narrative'])
                else:
                    st.warning("No results found. Try adjusting your filters or query.")
        else:
            st.warning("Please enter a search query")

else:  # Similar Players
    st.header("🔍 Find Similar Players")

    if st.button("🔍 Find Similar Players", type="primary"):
        if reference_player:
            with st.spinner(f"Finding players similar to {reference_player}..."):
                results = st.session_state.search_engine.find_similar_players(
                    player_name=reference_player,
                    same_position_only=same_position,
                    top_k=top_k
                )

                if results:
                    st.success(f"Found {len(results)} players similar to {reference_player}")

                    # Create dataframe
                    df = pd.DataFrame(results)
                    df['similarity'] = df['similarity'].apply(lambda x: f"{x:.4f}")
                    df = df.rename(columns={
                        'name': 'Player',
                        'position': 'Pos',
                        'seasons': 'Seasons',
                        'avg_points': 'Avg Pts/Season',
                        'similarity': 'Similarity'
                    })

                    st.dataframe(
                        df,
                        use_container_width=True,
                        hide_index=True
                    )

                    # Detailed results
                    st.subheader("📋 Detailed Comparison")
                    for i, player in enumerate(results, 1):
                        st.markdown(
                            f"**{i}. {player['name']}** ({player['position']}) • "
                            f"{player['seasons']} seasons • "
                            f"Avg {player['avg_points']} pts/season • "
                            f"Similarity: {player['similarity']:.4f}"
                        )
                else:
                    st.warning(f"No players found similar to '{reference_player}'. Try a different name.")
        else:
            st.warning("Please enter a player name")

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666;">
    <p><strong>NHL Semantic Analytics Platform</strong> • Built with Oracle 26ai Vector Search</p>
    <p>BU 779 Advanced Database Management • Spring 2026</p>
    <p>Features: Hybrid Search (Semantic + SQL Filters) • 9,745 Searchable Entities • Sub-10ms Queries</p>
</div>
""", unsafe_allow_html=True)
